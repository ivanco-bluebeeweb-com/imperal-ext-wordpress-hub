<?php
/**
 * Plugin Name:       Imperal Builder Bridge
 * Plugin URI:        https://panel.imperal.io
 * Description:       Exposes Elementor and Bricks page-builder element trees to the WordPress REST API, with guarded single-field point edits, so Imperal / Webbee can read and precisely edit builder content without touching the rest of the page.
 * Version:           1.2.0
 * Requires at least: 6.0
 * Requires PHP:      8.0
 * Author:            Imperal Cloud
 * Author URI:        https://imperal.io
 * License:           GPL v2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       imperal-builder-bridge
 *
 * ---------------------------------------------------------------------------
 * WHY THIS PLUGIN EXISTS
 *
 * Elementor stores its whole page tree in a single post meta key,
 * `_elementor_data`, as a JSON-encoded nested array (elType/widgetType/
 * settings/elements). Bricks stores each template area (header/content/
 * footer) in its own meta key (`_bricks_page_header_2`, `_bricks_page_content_2`,
 * `_bricks_page_footer_2`) as a JSON-encoded FLAT array keyed by element id,
 * with parent/children references.
 *
 * Neither plugin calls register_post_meta() for these keys, so stock
 * WordPress REST + an Application Password cannot see or edit them — reads
 * come back empty and writes are silently dropped, exactly like Rank Math's
 * rank_math_* meta before the SEO bridge. This plugin is that same fix,
 * scoped to builder content instead of SEO fields.
 *
 * ---------------------------------------------------------------------------
 * DESIGN NOTES — point editing, not page building
 *
 * This bridge deliberately does NOT expose "replace the whole tree" or
 * "create a new element" endpoints. Every write targets exactly one existing
 * element, identified by its builder-native id, and exactly one field inside
 * that element's settings. This mirrors the WooCommerce guarded-write pattern
 * already used elsewhere in this connector: preview shows a state_token
 * (a hash of the current tree), and the update call must echo that token back
 * or it is rejected — so a write can never silently clobber a page that
 * changed in the WordPress editor between preview and apply.
 *
 * Both formats are read and returned to the client as a FLATTENED list of
 * elements (id, parent_id, type, label, settings) — Elementor's naturally
 * nested tree is flattened server-side so callers do not need two different
 * shapes to reason about.
 * ---------------------------------------------------------------------------
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'IMPERAL_BUILDER_BRIDGE_VERSION', '1.2.0' );
define( 'IMPERAL_BUILDER_BRIDGE_NAMESPACE', 'imperal/v1' );

const IMPERAL_BUILDER_ELEMENTOR_META = '_elementor_data';
const IMPERAL_BUILDER_BRICKS_META    = array(
	'header'  => '_bricks_page_header_2',
	'content' => '_bricks_page_content_2',
	'footer'  => '_bricks_page_footer_2',
);

/**
 * Resolve a post from id or slug (+optional type), same contract as the SEO
 * bridge so both plugins feel identical from the client side.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_Post|WP_Error
 */
function imperal_builder_bridge_resolve_post( $request ) {
	$id   = (int) $request->get_param( 'id' );
	$slug = (string) $request->get_param( 'slug' );
	$type = (string) $request->get_param( 'type' );

	if ( $id > 0 ) {
		$post = get_post( $id );
		if ( ! $post instanceof WP_Post ) {
			return new WP_Error(
				'imperal_builder_not_found',
				__( 'No post or page with that id.', 'imperal-builder-bridge' ),
				array( 'status' => 404 )
			);
		}
		return $post;
	}

	if ( '' === trim( $slug ) ) {
		return new WP_Error(
			'imperal_builder_target_missing',
			__( 'Pass id or slug.', 'imperal-builder-bridge' ),
			array( 'status' => 400 )
		);
	}

	$args = array(
		'name'        => sanitize_title( $slug ),
		'post_status' => array( 'publish', 'draft', 'pending', 'private', 'future' ),
		'numberposts' => 2,
	);
	if ( '' !== trim( $type ) ) {
		$args['post_type'] = sanitize_key( $type );
	} else {
		$args['post_type'] = 'any';
	}

	$found = get_posts( $args );

	if ( empty( $found ) ) {
		return new WP_Error(
			'imperal_builder_not_found',
			__( 'No post or page with that slug.', 'imperal-builder-bridge' ),
			array( 'status' => 404 )
		);
	}

	if ( count( $found ) > 1 ) {
		return new WP_Error(
			'imperal_builder_ambiguous_slug',
			__( 'Several items share that slug — pass post_type to disambiguate.', 'imperal-builder-bridge' ),
			array( 'status' => 409 )
		);
	}

	return $found[0];
}

/**
 * Permission callback shared by every read/write route: the request must
 * resolve to a real post, and the current user must be able to edit it.
 *
 * @param WP_REST_Request $request Request.
 * @return true|WP_Error
 */
function imperal_builder_bridge_permission( $request ) {
	$post = imperal_builder_bridge_resolve_post( $request );

	if ( is_wp_error( $post ) ) {
		return $post;
	}

	if ( ! current_user_can( 'edit_post', $post->ID ) ) {
		return new WP_Error(
			'imperal_builder_forbidden',
			__( 'That WordPress user cannot edit this item.', 'imperal-builder-bridge' ),
			array( 'status' => 403 )
		);
	}

	return true;
}

/**
 * Which builder(s), if any, this post was built with.
 *
 * @param int $post_id Post id.
 * @return array List of active builder slugs among 'elementor', 'bricks'.
 */
function imperal_builder_bridge_active_builders( $post_id ) {
	$active = array();

	$elementor_data = get_post_meta( $post_id, IMPERAL_BUILDER_ELEMENTOR_META, true );
	if ( ! empty( imperal_builder_bridge_decode_meta( $elementor_data ) ) ) {
		$active[] = 'elementor';
	}

	foreach ( IMPERAL_BUILDER_BRICKS_META as $zone => $meta_key ) {
		$zone_data = get_post_meta( $post_id, $meta_key, true );
		if ( ! empty( imperal_builder_bridge_decode_meta( $zone_data ) ) ) {
			$active[] = 'bricks';
			break;
		}
	}

	return array_values( array_unique( $active ) );
}

/**
 * A stable hash of a builder's current stored state, used as the
 * concurrency guard (state_token). Any change to the raw meta value changes
 * this hash, so a stale-write attempt is caught before it overwrites
 * something the WordPress editor changed in the meantime.
 *
 * @param mixed $raw Raw meta value as returned by get_post_meta() — may be a
 *                    JSON string OR an already-unserialized PHP array. Both
 *                    are hashed to the SAME token for the same logical
 *                    content, since get_post_meta() silently auto-unserializes
 *                    PHP-serialized values, and either storage format is
 *                    legitimate depending on how the builder itself wrote it.
 * @return string sha256 hex digest.
 */
function imperal_builder_bridge_state_token( $raw ) {
	$decoded = imperal_builder_bridge_decode_meta( $raw );
	return hash( 'sha256', (string) wp_json_encode( $decoded ) );
}

/**
 * Normalize a raw post-meta value into a decoded array, regardless of
 * whether WordPress handed it back as a JSON string (typical when the
 * builder itself calls wp_json_encode() before storing) or as an
 * already-unserialized PHP array (get_post_meta() auto-unserializes any
 * value that was stored via PHP's serialize() format, which is what
 * update_post_meta() does by default when given an array/object).
 *
 * Root cause this fixes: earlier versions of this bridge assumed the meta
 * value was ALWAYS a JSON string and used `is_string( $raw ) ? $raw : '[]'`
 * before json_decode — so any post where the builder stored its data as a
 * native PHP array (auto-unserialized back to an array by WordPress) was
 * silently treated as empty, even though real content was there.
 *
 * @param mixed $raw Raw meta value as returned by get_post_meta().
 * @return array Decoded content, or an empty array if there is none.
 */
function imperal_builder_bridge_decode_meta( $raw ) {
	if ( is_array( $raw ) ) {
		return $raw;
	}
	if ( is_string( $raw ) && '' !== trim( $raw ) ) {
		$decoded = json_decode( $raw, true );
		if ( is_array( $decoded ) ) {
			return $decoded;
		}
	}
	return array();
}

/**
 * Recursively flatten Elementor's nested content tree into a flat list.
 *
 * Elementor nodes are { id, elType, widgetType?, settings, elements: [...] }.
 * We keep id, parent_id, elType, widgetType (widget label, empty for
 * section/column/container), and settings verbatim.
 *
 * @param array       $nodes     Elementor elements array.
 * @param string|null $parent_id Parent element id, or null at the root.
 * @return array Flat list of associative element rows.
 */
function imperal_builder_bridge_flatten_elementor( $nodes, $parent_id = null ) {
	$flat = array();

	if ( ! is_array( $nodes ) ) {
		return $flat;
	}

	foreach ( $nodes as $node ) {
		if ( ! is_array( $node ) ) {
			continue;
		}

		$id = isset( $node['id'] ) ? (string) $node['id'] : '';
		if ( '' === $id ) {
			continue;
		}

		$flat[] = array(
			'id'         => $id,
			'parent_id'  => $parent_id,
			'el_type'    => isset( $node['elType'] ) ? (string) $node['elType'] : '',
			'widget_type' => isset( $node['widgetType'] ) ? (string) $node['widgetType'] : '',
			'settings'   => isset( $node['settings'] ) && is_array( $node['settings'] ) ? $node['settings'] : array(),
		);

		if ( isset( $node['elements'] ) && is_array( $node['elements'] ) ) {
			$flat = array_merge( $flat, imperal_builder_bridge_flatten_elementor( $node['elements'], $id ) );
		}
	}

	return $flat;
}

/**
 * Find and replace one element's node in Elementor's nested tree in place,
 * by id, applying a callback to its settings array. Returns true if found.
 *
 * @param array    $nodes    Elementor elements array, passed by reference.
 * @param string   $id       Target element id.
 * @param callable $mutator  function( array $settings ): array
 * @return bool Whether the element was found and mutated.
 */
function imperal_builder_bridge_mutate_elementor( &$nodes, $id, $mutator ) {
	if ( ! is_array( $nodes ) ) {
		return false;
	}

	foreach ( $nodes as &$node ) {
		if ( ! is_array( $node ) ) {
			continue;
		}

		if ( isset( $node['id'] ) && (string) $node['id'] === $id ) {
			$settings          = isset( $node['settings'] ) && is_array( $node['settings'] ) ? $node['settings'] : array();
			$node['settings']  = call_user_func( $mutator, $settings );
			return true;
		}

		if ( isset( $node['elements'] ) && is_array( $node['elements'] ) ) {
			if ( imperal_builder_bridge_mutate_elementor( $node['elements'], $id, $mutator ) ) {
				return true;
			}
		}
	}
	unset( $node );

	return false;
}

/**
 * Flatten a Bricks zone (already-flat array of element rows) into the same
 * shape used for Elementor, so both builders share one response contract.
 *
 * Bricks elements look like: { id, name, parent, children: [...], settings,
 * label? }. 'name' is Bricks' widget/element type (e.g. "heading", "container").
 *
 * @param array  $nodes Bricks elements array (flat, from JSON decode).
 * @param string $zone  Zone name ('header'|'content'|'footer'), carried through.
 * @return array Flat list of associative element rows.
 */
function imperal_builder_bridge_flatten_bricks( $nodes, $zone ) {
	$flat = array();

	if ( ! is_array( $nodes ) ) {
		return $flat;
	}

	foreach ( $nodes as $node ) {
		if ( ! is_array( $node ) || ! isset( $node['id'] ) ) {
			continue;
		}

		$flat[] = array(
			'id'          => (string) $node['id'],
			'parent_id'   => isset( $node['parent'] ) && '' !== (string) $node['parent'] && 0 !== $node['parent']
				? (string) $node['parent'] : null,
			'el_type'     => isset( $node['name'] ) ? (string) $node['name'] : '',
			'widget_type' => isset( $node['label'] ) ? (string) $node['label'] : '',
			'settings'    => isset( $node['settings'] ) && is_array( $node['settings'] ) ? $node['settings'] : array(),
			'zone'        => $zone,
		);
	}

	return $flat;
}

/**
 * Update one field inside one Bricks element's settings, by id, in the
 * flat array in place. Returns true if found.
 *
 * @param array    $nodes   Bricks elements array, passed by reference.
 * @param string   $id      Target element id.
 * @param callable $mutator function( array $settings ): array
 * @return bool Whether the element was found and mutated.
 */
function imperal_builder_bridge_mutate_bricks( &$nodes, $id, $mutator ) {
	if ( ! is_array( $nodes ) ) {
		return false;
	}

	foreach ( $nodes as &$node ) {
		if ( ! is_array( $node ) || ! isset( $node['id'] ) ) {
			continue;
		}
		if ( (string) $node['id'] === $id ) {
			$settings         = isset( $node['settings'] ) && is_array( $node['settings'] ) ? $node['settings'] : array();
			$node['settings'] = call_user_func( $mutator, $settings );
			return true;
		}
	}
	unset( $node );

	return false;
}

/**
 * GET /imperal/v1/builder/scan — diagnostic: which posts/pages/templates on
 * this site actually carry non-empty builder meta, across ALL post types
 * (including custom ones like `bricks_template` that plain list_pages /
 * list_posts calls never see, since they are not registered for the normal
 * REST posts endpoints). Read-only, capped, for figuring out WHERE builder
 * content actually lives before trying to read/edit a specific item.
 *
 * @return WP_REST_Response
 */
function imperal_builder_bridge_scan() {
	global $wpdb;

	// Discover every post_type/id pair that has ANY of our meta keys
	// non-empty and non-'[]', in one query against postmeta — cheaper and
	// more honest than looping get_posts() per public post type, and it
	// also reaches non-public / non-REST-exposed types like bricks_template.
	$meta_keys = array_merge(
		array( IMPERAL_BUILDER_ELEMENTOR_META ),
		array_values( IMPERAL_BUILDER_BRICKS_META )
	);
	$placeholders = implode( ',', array_fill( 0, count( $meta_keys ), '%s' ) );

	// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	$sql = $wpdb->prepare(
		"SELECT pm.post_id, pm.meta_key, p.post_type, p.post_title, p.post_status
		 FROM {$wpdb->postmeta} pm
		 INNER JOIN {$wpdb->posts} p ON p.ID = pm.post_id
		 WHERE pm.meta_key IN ($placeholders)
		 AND pm.meta_value IS NOT NULL
		 AND pm.meta_value != ''
		 AND pm.meta_value != '[]'
		 ORDER BY p.post_type, pm.post_id
		 LIMIT 500",
		$meta_keys
	);

	$rows = $wpdb->get_results( $sql );

	$by_post = array();
	foreach ( (array) $rows as $row ) {
		$id = (int) $row->post_id;
		if ( ! isset( $by_post[ $id ] ) ) {
			$by_post[ $id ] = array(
				'id'          => $id,
				'title'       => $row->post_title,
				'type'        => $row->post_type,
				'status'      => $row->post_status,
				'builders'    => array(),
				'meta_keys'   => array(),
			);
		}
		$by_post[ $id ]['meta_keys'][] = $row->meta_key;
		$builder = ( IMPERAL_BUILDER_ELEMENTOR_META === $row->meta_key ) ? 'elementor' : 'bricks';
		if ( ! in_array( $builder, $by_post[ $id ]['builders'], true ) ) {
			$by_post[ $id ]['builders'][] = $builder;
		}
	}

	// Also surface which registered post types exist at all (helps explain
	// e.g. why list_custom_posts('bricks_template') 404s: the type may not
	// be REST-exposed even though it holds real builder content here).
	$post_types = get_post_types( array(), 'names' );

	return rest_ensure_response(
		array(
			'items_with_builder_content' => array_values( $by_post ),
			'total_found'                => count( $by_post ),
			'registered_post_types'      => array_values( $post_types ),
		)
	);
}

/**
 * GET /imperal/v1/builder — read the flattened element tree for one post,
 * across whichever builder(s) are active on it.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_builder_bridge_get_tree( $request ) {
	$post = imperal_builder_bridge_resolve_post( $request );
	if ( is_wp_error( $post ) ) {
		return $post;
	}

	$requested_builder = strtolower( (string) $request->get_param( 'builder' ) );
	$active             = imperal_builder_bridge_active_builders( $post->ID );

	if ( empty( $active ) ) {
		return new WP_Error(
			'imperal_builder_none_active',
			__( 'This item was not built with Elementor or Bricks — no builder content to read.', 'imperal-builder-bridge' ),
			array( 'status' => 404 )
		);
	}

	if ( '' !== $requested_builder && ! in_array( $requested_builder, $active, true ) ) {
		return new WP_Error(
			'imperal_builder_not_active',
			sprintf(
				/* translators: 1: requested builder, 2: comma-separated active builders */
				__( '%1$s is not active on this item. Active builder(s): %2$s.', 'imperal-builder-bridge' ),
				$requested_builder,
				implode( ', ', $active )
			),
			array( 'status' => 404 )
		);
	}

	$builders_out = array();

	if ( in_array( 'elementor', $active, true ) && ( '' === $requested_builder || 'elementor' === $requested_builder ) ) {
		$raw     = get_post_meta( $post->ID, IMPERAL_BUILDER_ELEMENTOR_META, true );
		$decoded = imperal_builder_bridge_decode_meta( $raw );

		$flat = imperal_builder_bridge_flatten_elementor( $decoded );

		$builders_out['elementor'] = array(
			'elements'      => $flat,
			'state_token'   => imperal_builder_bridge_state_token( $raw ),
			'element_count' => count( $flat ),
		);
	}

	if ( in_array( 'bricks', $active, true ) && ( '' === $requested_builder || 'bricks' === $requested_builder ) ) {
		$zones = array();
		foreach ( IMPERAL_BUILDER_BRICKS_META as $zone => $meta_key ) {
			$raw     = get_post_meta( $post->ID, $meta_key, true );
			$decoded = imperal_builder_bridge_decode_meta( $raw );
			$zones[ $zone ] = array(
				'elements'    => imperal_builder_bridge_flatten_bricks( $decoded, $zone ),
				'state_token' => imperal_builder_bridge_state_token( $raw ),
			);
		}
		$builders_out['bricks'] = array( 'zones' => $zones );
	}

	return rest_ensure_response(
		array(
			'id'              => $post->ID,
			'slug'            => $post->post_name,
			'type'            => $post->post_type,
			'link'            => get_permalink( $post ),
			'active_builders' => $active,
			'builders'        => $builders_out,
		)
	);
}

/**
 * Write a decoded builder tree back to post meta, preserving whichever
 * storage format the ORIGINAL raw value was in — a native PHP array (which
 * WordPress will re-serialize via serialize(), exactly as update_post_meta()
 * does by default for array/object values) or a JSON string (if the builder
 * itself always wp_json_encode()s before storing).
 *
 * This matters because Bricks/Elementor read their own meta with
 * get_post_meta() too: if we always wrote back a JSON STRING regardless of
 * how the value was originally stored, a site that stores it as a native
 * array would suddenly get a JSON string back on its next read — which the
 * builder's own PHP does not expect and would silently fail to render or
 * edit correctly. Round-tripping the same shape keeps both sides working.
 *
 * @param int    $post_id  Post id.
 * @param string $meta_key Meta key to write.
 * @param mixed  $raw      The raw value as originally returned by
 *                          get_post_meta() before this edit — decides the
 *                          format to write back.
 * @param array  $decoded  The mutated, decoded content to persist.
 * @return void
 */
function imperal_builder_bridge_write_meta( $post_id, $meta_key, $raw, $decoded ) {
	if ( is_array( $raw ) ) {
		// Originally a native PHP array — write it back the same way so
		// WordPress serializes it, matching how the builder itself stored it.
		update_post_meta( $post_id, $meta_key, $decoded );
		return;
	}
	// Originally a JSON string (or empty/missing) — keep writing JSON.
	update_post_meta( $post_id, $meta_key, wp_slash( wp_json_encode( $decoded ) ) );
}

/**
 * POST /imperal/v1/builder/field — set exactly one settings field on exactly
 * one existing element, guarded by state_token.
 *
 * Body: { id (post), element_id, field, value, state_token, builder?, zone? }
 * builder is required when both Elementor and Bricks are active on the post.
 * zone is required for Bricks (header|content|footer).
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_builder_bridge_update_field( $request ) {
	$post = imperal_builder_bridge_resolve_post( $request );
	if ( is_wp_error( $post ) ) {
		return $post;
	}

	$element_id  = (string) $request->get_param( 'element_id' );
	$field       = (string) $request->get_param( 'field' );
	$state_token = (string) $request->get_param( 'state_token' );
	$builder     = strtolower( (string) $request->get_param( 'builder' ) );
	$zone        = strtolower( (string) $request->get_param( 'zone' ) );

	if ( '' === trim( $element_id ) ) {
		return new WP_Error( 'imperal_builder_element_missing', __( 'element_id is required.', 'imperal-builder-bridge' ), array( 'status' => 400 ) );
	}
	if ( '' === trim( $field ) ) {
		return new WP_Error( 'imperal_builder_field_missing', __( 'field is required.', 'imperal-builder-bridge' ), array( 'status' => 400 ) );
	}
	if ( ! $request->has_param( 'value' ) ) {
		return new WP_Error( 'imperal_builder_value_missing', __( 'value is required.', 'imperal-builder-bridge' ), array( 'status' => 400 ) );
	}
	if ( '' === trim( $state_token ) ) {
		return new WP_Error( 'imperal_builder_state_token_missing', __( 'state_token is required — call the read endpoint first.', 'imperal-builder-bridge' ), array( 'status' => 400 ) );
	}

	$value  = $request->get_param( 'value' );
	$active = imperal_builder_bridge_active_builders( $post->ID );

	if ( '' === $builder ) {
		if ( count( $active ) > 1 ) {
			return new WP_Error(
				'imperal_builder_ambiguous_builder',
				__( 'Both Elementor and Bricks are active on this item — pass builder to disambiguate.', 'imperal-builder-bridge' ),
				array( 'status' => 409 )
			);
		}
		if ( empty( $active ) ) {
			return new WP_Error(
				'imperal_builder_none_active',
				__( 'This item was not built with Elementor or Bricks.', 'imperal-builder-bridge' ),
				array( 'status' => 404 )
			);
		}
		$builder = $active[0];
	}

	if ( ! in_array( $builder, array( 'elementor', 'bricks' ), true ) ) {
		return new WP_Error( 'imperal_builder_unknown', __( "builder must be 'elementor' or 'bricks'.", 'imperal-builder-bridge' ), array( 'status' => 400 ) );
	}

	if ( ! in_array( $builder, $active, true ) ) {
		return new WP_Error(
			'imperal_builder_not_active',
			sprintf(
				/* translators: %s: builder name */
				__( '%s is not active on this item.', 'imperal-builder-bridge' ),
				$builder
			),
			array( 'status' => 404 )
		);
	}

	if ( 'elementor' === $builder ) {
		$meta_key = IMPERAL_BUILDER_ELEMENTOR_META;
		$raw      = get_post_meta( $post->ID, $meta_key, true );

		if ( imperal_builder_bridge_state_token( $raw ) !== $state_token ) {
			return new WP_Error(
				'imperal_builder_stale_state',
				__( 'This page changed since you read it — read it again and retry with the fresh state_token.', 'imperal-builder-bridge' ),
				array( 'status' => 409 )
			);
		}

		$decoded = imperal_builder_bridge_decode_meta( $raw );

		$found = imperal_builder_bridge_mutate_elementor(
			$decoded,
			$element_id,
			function ( $settings ) use ( $field, $value ) {
				$settings[ $field ] = $value;
				return $settings;
			}
		);

		if ( ! $found ) {
			return new WP_Error(
				'imperal_builder_element_not_found',
				__( 'No element with that id in the Elementor tree.', 'imperal-builder-bridge' ),
				array( 'status' => 404 )
			);
		}

		imperal_builder_bridge_write_meta( $post->ID, $meta_key, $raw, $decoded );

		// Elementor caches rendered CSS per element — clear it so the edit
		// shows up immediately instead of a stale cached render.
		delete_post_meta( $post->ID, '_elementor_css' );
		if ( class_exists( '\Elementor\Plugin' ) ) {
			try {
				\Elementor\Plugin::$instance->files_manager->clear_cache();
			} catch ( \Throwable $e ) {
				// Best-effort — the meta write already succeeded either way.
				unset( $e );
			}
		}

		return rest_ensure_response(
			array(
				'id'          => $post->ID,
				'builder'     => 'elementor',
				'element_id'  => $element_id,
				'field'       => $field,
				'state_token' => imperal_builder_bridge_state_token( $decoded ),
			)
		);
	}

	// Bricks.
	if ( '' === $zone || ! isset( IMPERAL_BUILDER_BRICKS_META[ $zone ] ) ) {
		return new WP_Error(
			'imperal_builder_zone_missing',
			__( "zone is required for Bricks and must be 'header', 'content' or 'footer'.", 'imperal-builder-bridge' ),
			array( 'status' => 400 )
		);
	}

	$meta_key = IMPERAL_BUILDER_BRICKS_META[ $zone ];
	$raw      = get_post_meta( $post->ID, $meta_key, true );

	if ( imperal_builder_bridge_state_token( $raw ) !== $state_token ) {
		return new WP_Error(
			'imperal_builder_stale_state',
			__( 'This page changed since you read it — read it again and retry with the fresh state_token.', 'imperal-builder-bridge' ),
			array( 'status' => 409 )
		);
	}

	$decoded = imperal_builder_bridge_decode_meta( $raw );

	$found = imperal_builder_bridge_mutate_bricks(
		$decoded,
		$element_id,
		function ( $settings ) use ( $field, $value ) {
			$settings[ $field ] = $value;
			return $settings;
		}
	);

	if ( ! $found ) {
		return new WP_Error(
			'imperal_builder_element_not_found',
			sprintf(
				/* translators: %s: zone name */
				__( 'No element with that id in the Bricks %s zone.', 'imperal-builder-bridge' ),
				$zone
			),
			array( 'status' => 404 )
		);
	}

	imperal_builder_bridge_write_meta( $post->ID, $meta_key, $raw, $decoded );

	return rest_ensure_response(
		array(
			'id'          => $post->ID,
			'builder'     => 'bricks',
			'zone'        => $zone,
			'element_id'  => $element_id,
			'field'       => $field,
			'state_token' => imperal_builder_bridge_state_token( $decoded ),
		)
	);
}

/**
 * GET /imperal/v1/builder/status — capability discovery: is the bridge
 * present, and which builder plugins are active site-wide (not just on one
 * post — Elementor/Bricks activation is a whole-site fact).
 *
 * @return WP_REST_Response
 */
function imperal_builder_bridge_status() {
	return rest_ensure_response(
		array(
			'bridge'            => true,
			'bridge_version'    => IMPERAL_BUILDER_BRIDGE_VERSION,
			'elementor_active'  => defined( 'ELEMENTOR_VERSION' ),
			'elementor_version' => defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : '',
			'bricks_active'     => function_exists( 'bricks_is_builder' ) || defined( 'BRICKS_VERSION' ),
			'bricks_version'    => defined( 'BRICKS_VERSION' ) ? BRICKS_VERSION : '',
		)
	);
}

/**
 * Register the REST routes.
 */
function imperal_builder_bridge_register_routes() {
	register_rest_route(
		IMPERAL_BUILDER_BRIDGE_NAMESPACE,
		'/builder',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_builder_bridge_get_tree',
				'permission_callback' => 'imperal_builder_bridge_permission',
				'args'                => array(
					'id'      => array( 'type' => 'integer' ),
					'slug'    => array( 'type' => 'string' ),
					'type'    => array( 'type' => 'string' ),
					'builder' => array( 'type' => 'string' ),
				),
			),
		)
	);

	register_rest_route(
		IMPERAL_BUILDER_BRIDGE_NAMESPACE,
		'/builder/field',
		array(
			array(
				'methods'             => WP_REST_Server::EDITABLE,
				'callback'            => 'imperal_builder_bridge_update_field',
				'permission_callback' => 'imperal_builder_bridge_permission',
				'args'                => array(
					'id'          => array( 'type' => 'integer' ),
					'slug'        => array( 'type' => 'string' ),
					'type'        => array( 'type' => 'string' ),
					'builder'     => array( 'type' => 'string' ),
					'zone'        => array( 'type' => 'string' ),
					'element_id'  => array( 'type' => 'string', 'required' => true ),
					'field'       => array( 'type' => 'string', 'required' => true ),
					'state_token' => array( 'type' => 'string', 'required' => true ),
				),
			),
		)
	);

	register_rest_route(
		IMPERAL_BUILDER_BRIDGE_NAMESPACE,
		'/builder/status',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_builder_bridge_status',
				'permission_callback' => function () {
					return current_user_can( 'edit_posts' );
				},
			),
		)
	);

	register_rest_route(
		IMPERAL_BUILDER_BRIDGE_NAMESPACE,
		'/builder/scan',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_builder_bridge_scan',
				'permission_callback' => function () {
					return current_user_can( 'edit_posts' );
				},
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_builder_bridge_register_routes' );

/**
 * Mark our own routes uncacheable so a page cache (LiteSpeed etc.) never
 * serves a stale read straight after a write — the same fix already applied
 * in the SEO bridge, learned the hard way from a live LiteSpeed site.
 */
add_filter(
	'rest_post_dispatch',
	function ( $response, $server, $request ) {
		$route = $request->get_route();
		if ( 0 === strpos( $route, '/' . IMPERAL_BUILDER_BRIDGE_NAMESPACE . '/builder' ) ) {
			$response->header( 'Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0' );
		}
		return $response;
	},
	10,
	3
);

<?php
/**
 * Plugin Name:       Imperal SEO Bridge
 * Plugin URI:        https://panel.imperal.io
 * Description:       Exposes Rank Math SEO fields (title, description, focus keyword, robots, canonical, schema/rich-snippet type) to the WordPress REST API so Imperal / Webbee can read and edit them for posts, pages, custom post types and taxonomy terms (categories, tags).
 * Version:           1.2.0
 * Requires at least: 6.0
 * Requires PHP:      8.0
 * Author:            Imperal Cloud
 * Author URI:        https://imperal.io
 * License:           GPL v2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       imperal-seo-bridge
 *
 * ---------------------------------------------------------------------------
 * WHY THIS PLUGIN EXISTS
 *
 * Rank Math never calls register_post_meta() / register_meta() anywhere in its
 * codebase (verified against seo-by-rank-math 1.0.274.1). WordPress core only
 * exposes meta over the REST API when it is registered with show_in_rest, so
 * without a bridge like this one the rank_math_* fields are simply invisible
 * to the REST API — reads come back empty and writes are silently dropped.
 *
 * On top of that, Rank Math marks every rank_math_* key as protected meta
 * (includes/class-common.php -> hide_rank_math_meta). Core falls back to
 * auth_callback = __return_false for protected keys, so an explicit
 * auth_callback is required or every write fails with rest_cannot_update.
 *
 * ---------------------------------------------------------------------------
 * DESIGN NOTES
 *
 * 1. Only the STRING fields are registered on the standard post/page/CPT
 *    endpoints. rank_math_robots is stored by Rank Math as an ARRAY
 *    (see includes/admin/class-post-columns.php -> FILTER_REQUIRE_ARRAY and
 *    the importers calling update_post_meta( $id, 'rank_math_robots', [] )).
 *    Registering an array meta on a collection endpoint is risky: legacy rows
 *    may hold a scalar, and core's WP_REST_Meta_Fields would then try to
 *    serialise it against an array schema. Rather than put the existing
 *    /wp/v2/posts listing at risk, robots and canonical are served through
 *    this plugin's own namespaced endpoint, where we control the shape.
 *
 * 2. Values are sanitised exactly the way Rank Math sanitises them in
 *    includes/rest/class-sanitize.php:
 *      - title / description  -> wp_filter_nohtml_kses()
 *      - canonical url        -> esc_url_raw()
 *    Robots values are validated against Rank Math's own allow-list from
 *    includes/helpers/class-choices.php -> choices_robots().
 *
 * 3. Permission checks are per-object ('edit_post', $id), never a blanket
 *    'edit_posts'. Core registers 'post' with capability_type 'post' and
 *    'page' with capability_type 'page', so only the per-object meta cap maps
 *    correctly for both.
 *
 * 4. Empty values delete the meta row rather than storing an empty string,
 *    matching Rank Math's own REST behaviour (includes/rest/class-shared.php)
 *    so the plugin's "no custom title set" state stays truthful.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'IMPERAL_SEO_BRIDGE_VERSION', '1.2.0' );
define( 'IMPERAL_SEO_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * String meta fields safe to expose on the standard REST endpoints.
 *
 * @return array<string,string> meta key => sanitiser id
 */
function imperal_seo_bridge_string_fields() {
	return array(
		'rank_math_title'         => 'text',
		'rank_math_description'   => 'text',
		'rank_math_focus_keyword' => 'text',
		'rank_math_canonical_url' => 'url',
		// Schema/rich-snippet type, e.g. 'Article', 'Product', 'off' when disabled.
		// Rank Math (and its PRO schema templates / custom schema module) accept an
		// open-ended set of schema.org type names here, not a small fixed list, so
		// this is treated as free text and sanitised the same way as title/description
		// rather than validated against an invented enum.
		'rank_math_rich_snippet'  => 'text',
	);
}

/**
 * Robots values Rank Math itself accepts.
 *
 * Mirrors RankMath\Helpers\Choices::choices_robots().
 *
 * @return string[]
 */
function imperal_seo_bridge_robots_choices() {
	return array( 'index', 'noindex', 'nofollow', 'noarchive', 'noimageindex', 'nosnippet' );
}

/**
 * Post types the bridge covers: every public type with REST + custom-fields.
 *
 * Core registers both 'post' and 'page' with 'custom-fields' support, which is
 * what makes registered meta appear on their REST endpoints. Custom post types
 * are included when they opt into the same two things.
 *
 * @return string[]
 */
function imperal_seo_bridge_post_types() {
	$types = get_post_types( array( 'show_in_rest' => true ), 'names' );
	$out   = array();

	foreach ( $types as $type ) {
		if ( 'attachment' === $type ) {
			continue;
		}
		if ( ! post_type_supports( $type, 'custom-fields' ) ) {
			continue;
		}
		$out[] = $type;
	}

	/**
	 * Filter the post types the Imperal SEO Bridge registers meta for.
	 *
	 * @param string[] $out Post type names.
	 */
	return apply_filters( 'imperal_seo_bridge_post_types', $out );
}

/**
 * Taxonomies the bridge covers: every public taxonomy exposed to REST.
 *
 * Terms carry the same rank_math_* keys as posts — confirmed in Rank Math
 * itself, which switches only the storage call and keeps the key names
 * (includes/rest/class-post.php: `$method = $object_type === 'term' ?
 * 'update_term_meta' : 'update_post_meta'`, same `rank_math_` prefix), and in
 * its Yoast importer, which maps wpseo_title => rank_math_title /
 * wpseo_desc => rank_math_description for term meta.
 *
 * @return string[]
 */
function imperal_seo_bridge_taxonomies() {
	$taxes = get_taxonomies( array( 'show_in_rest' => true ), 'names' );
	$out   = array();

	foreach ( $taxes as $tax ) {
		// Menu/pattern plumbing carries no SEO meaning.
		if ( in_array( $tax, array( 'nav_menu', 'link_category', 'wp_pattern_category', 'post_format' ), true ) ) {
			continue;
		}
		$out[] = $tax;
	}

	/**
	 * Filter the taxonomies the Imperal SEO Bridge registers meta for.
	 *
	 * @param string[] $out Taxonomy names.
	 */
	return apply_filters( 'imperal_seo_bridge_taxonomies', $out );
}

/**
 * Can the current user edit this specific term's SEO meta?
 *
 * Uses the `edit_term` meta capability rather than a flat `manage_categories`,
 * because WordPress maps it through each taxonomy's own capability set — the
 * term-side equivalent of post vs page having different capability_type.
 *
 * @param int $term_id Term ID.
 * @return bool
 */
function imperal_seo_bridge_can_edit_term( $term_id ) {
	$term_id = (int) $term_id;

	if ( $term_id <= 0 ) {
		return false;
	}

	return current_user_can( 'edit_term', $term_id );
}

/**
 * Can the current user edit this specific object's SEO meta?
 *
 * @param int $post_id Post ID.
 * @return bool
 */
function imperal_seo_bridge_can_edit( $post_id ) {
	$post_id = (int) $post_id;

	if ( $post_id <= 0 ) {
		return false;
	}

	return current_user_can( 'edit_post', $post_id );
}

/**
 * Sanitise a value the same way Rank Math does.
 *
 * @param string $kind  'text' or 'url'.
 * @param mixed  $value Raw value.
 * @return string
 */
function imperal_seo_bridge_sanitize( $kind, $value ) {
	if ( ! is_scalar( $value ) ) {
		return '';
	}

	$value = (string) $value;

	if ( 'url' === $kind ) {
		return esc_url_raw( $value );
	}

	return wp_filter_nohtml_kses( $value );
}

/**
 * Register the string meta fields on every covered post type.
 */
function imperal_seo_bridge_register_meta() {
	$fields = imperal_seo_bridge_string_fields();

	foreach ( imperal_seo_bridge_post_types() as $post_type ) {
		foreach ( $fields as $key => $kind ) {
			register_post_meta(
				$post_type,
				$key,
				array(
					'show_in_rest'      => true,
					'single'            => true,
					'type'              => 'string',
					'default'           => '',
					'sanitize_callback' => function ( $value ) use ( $kind ) {
						return imperal_seo_bridge_sanitize( $kind, $value );
					},
					'auth_callback'     => function ( $allowed, $meta_key, $post_id ) {
						return imperal_seo_bridge_can_edit( $post_id );
					},
				)
			);
		}
	}
}
add_action( 'init', 'imperal_seo_bridge_register_meta', 20 );

/**
 * Register the string meta fields on every covered taxonomy.
 *
 * Same keys and sanitisers as posts; only the registration call and the
 * capability check differ.
 */
function imperal_seo_bridge_register_term_meta() {
	$fields = imperal_seo_bridge_string_fields();

	foreach ( imperal_seo_bridge_taxonomies() as $taxonomy ) {
		foreach ( $fields as $key => $kind ) {
			register_term_meta(
				$taxonomy,
				$key,
				array(
					'show_in_rest'      => true,
					'single'            => true,
					'type'              => 'string',
					'default'           => '',
					'sanitize_callback' => function ( $value ) use ( $kind ) {
						return imperal_seo_bridge_sanitize( $kind, $value );
					},
					'auth_callback'     => function ( $allowed, $meta_key, $term_id ) {
						return imperal_seo_bridge_can_edit_term( $term_id );
					},
				)
			);
		}
	}
}
add_action( 'init', 'imperal_seo_bridge_register_term_meta', 20 );

/**
 * Read the stored robots list for a term, normalised to a flat string array.
 *
 * @param int $term_id Term ID.
 * @return string[]
 */
function imperal_seo_bridge_get_term_robots( $term_id ) {
	return imperal_seo_bridge_normalise_robots( get_term_meta( $term_id, 'rank_math_robots', true ) );
}

/**
 * Read the stored robots list for a post, normalised to a flat string array.
 *
 * @param int $post_id Post ID.
 * @return string[]
 */
/**
 * Normalise a stored robots value to a flat, whitelisted string array.
 *
 * Shared by the post and term readers so the legacy-scalar and whitelist
 * handling cannot drift between them.
 *
 * @param mixed $stored Raw meta value.
 * @return string[]
 */
function imperal_seo_bridge_normalise_robots( $stored ) {
	if ( empty( $stored ) ) {
		return array();
	}

	// Legacy rows may hold a scalar instead of an array.
	if ( is_string( $stored ) ) {
		$stored = array( $stored );
	}

	if ( ! is_array( $stored ) ) {
		return array();
	}

	$allowed = imperal_seo_bridge_robots_choices();
	$clean   = array();

	foreach ( $stored as $value ) {
		if ( ! is_scalar( $value ) ) {
			continue;
		}
		$value = strtolower( trim( (string) $value ) );
		if ( in_array( $value, $allowed, true ) ) {
			$clean[] = $value;
		}
	}

	return array_values( array_unique( $clean ) );
}

function imperal_seo_bridge_get_robots( $post_id ) {
	return imperal_seo_bridge_normalise_robots( get_post_meta( $post_id, 'rank_math_robots', true ) );
}

/**
 * Build the SEO payload for one post.
 *
 * @param WP_Post $post Post object.
 * @return array
 */
function imperal_seo_bridge_payload( $post ) {
	return array(
		'id'               => (int) $post->ID,
		'slug'             => (string) $post->post_name,
		'type'             => (string) $post->post_type,
		'status'           => (string) $post->post_status,
		'link'             => (string) get_permalink( $post ),
		'post_title'       => (string) get_the_title( $post ),
		'meta_title'       => (string) get_post_meta( $post->ID, 'rank_math_title', true ),
		'meta_description' => (string) get_post_meta( $post->ID, 'rank_math_description', true ),
		'focus_keyword'    => (string) get_post_meta( $post->ID, 'rank_math_focus_keyword', true ),
		'canonical_url'    => (string) get_post_meta( $post->ID, 'rank_math_canonical_url', true ),
		'rich_snippet'     => (string) get_post_meta( $post->ID, 'rank_math_rich_snippet', true ),
		'robots'           => imperal_seo_bridge_get_robots( $post->ID ),
	);
}

/**
 * Resolve a post by numeric id or by slug.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_Post|WP_Error
 */
function imperal_seo_bridge_resolve_post( $request ) {
	$id   = (int) $request->get_param( 'id' );
	$slug = (string) $request->get_param( 'slug' );
	$type = (string) $request->get_param( 'type' );

	if ( $id > 0 ) {
		$post = get_post( $id );

		if ( ! $post instanceof WP_Post ) {
			return new WP_Error(
				'imperal_seo_not_found',
				__( 'No post or page with that id.', 'imperal-seo-bridge' ),
				array( 'status' => 404 )
			);
		}

		return $post;
	}

	if ( '' === $slug ) {
		return new WP_Error(
			'imperal_seo_missing_target',
			__( 'Provide either id or slug.', 'imperal-seo-bridge' ),
			array( 'status' => 400 )
		);
	}

	$types = '' !== $type ? array( $type ) : imperal_seo_bridge_post_types();

	$found = get_posts(
		array(
			'name'             => $slug,
			'post_type'        => $types,
			'post_status'      => array( 'publish', 'future', 'draft', 'pending', 'private' ),
			'numberposts'      => 2,
			'suppress_filters' => false,
		)
	);

	if ( empty( $found ) ) {
		return new WP_Error(
			'imperal_seo_not_found',
			__( 'No post or page with that slug.', 'imperal-seo-bridge' ),
			array( 'status' => 404 )
		);
	}

	if ( count( $found ) > 1 ) {
		return new WP_Error(
			'imperal_seo_ambiguous_slug',
			__( 'That slug matches more than one item — pass the numeric id instead.', 'imperal-seo-bridge' ),
			array( 'status' => 409 )
		);
	}

	return $found[0];
}

/**
 * Build the SEO payload for one term.
 *
 * Deliberately uses the SAME key names as the post payload (`id`, `type`,
 * `slug`, `link`, `post_title`, `meta_*`, `robots`) so the client needs no
 * second dialect; `type` carries the taxonomy name and `taxonomy` is added
 * for callers that want it explicitly.
 *
 * @param WP_Term $term Term object.
 * @return array
 */
function imperal_seo_bridge_term_payload( $term ) {
	$link = get_term_link( $term );

	return array(
		'id'               => (int) $term->term_id,
		'slug'             => (string) $term->slug,
		'type'             => (string) $term->taxonomy,
		'taxonomy'         => (string) $term->taxonomy,
		'object'           => 'term',
		'status'           => 'publish',
		'link'             => is_wp_error( $link ) ? '' : (string) $link,
		'post_title'       => (string) $term->name,
		'meta_title'       => (string) get_term_meta( $term->term_id, 'rank_math_title', true ),
		'meta_description' => (string) get_term_meta( $term->term_id, 'rank_math_description', true ),
		'focus_keyword'    => (string) get_term_meta( $term->term_id, 'rank_math_focus_keyword', true ),
		'canonical_url'    => (string) get_term_meta( $term->term_id, 'rank_math_canonical_url', true ),
		'rich_snippet'     => (string) get_term_meta( $term->term_id, 'rank_math_rich_snippet', true ),
		'robots'           => imperal_seo_bridge_get_term_robots( $term->term_id ),
	);
}

/**
 * Resolve a term by numeric id or by slug.
 *
 * Mirrors the post resolver, including refusing to guess when a slug matches
 * more than one term.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_Term|WP_Error
 */
function imperal_seo_bridge_resolve_term( $request ) {
	$id       = (int) $request->get_param( 'id' );
	$slug     = (string) $request->get_param( 'slug' );
	$taxonomy = (string) $request->get_param( 'taxonomy' );

	if ( '' === $taxonomy ) {
		$taxonomy = (string) $request->get_param( 'type' );
	}

	if ( $id > 0 ) {
		$term = '' !== $taxonomy ? get_term( $id, $taxonomy ) : get_term( $id );

		if ( is_wp_error( $term ) || ! $term instanceof WP_Term ) {
			return new WP_Error(
				'imperal_seo_not_found',
				__( 'No term with that id.', 'imperal-seo-bridge' ),
				array( 'status' => 404 )
			);
		}

		return $term;
	}

	if ( '' === $slug ) {
		return new WP_Error(
			'imperal_seo_missing_target',
			__( 'Provide either id or slug.', 'imperal-seo-bridge' ),
			array( 'status' => 400 )
		);
	}

	$taxonomies = '' !== $taxonomy ? array( $taxonomy ) : imperal_seo_bridge_taxonomies();

	$found = get_terms(
		array(
			'slug'       => $slug,
			'taxonomy'   => $taxonomies,
			'hide_empty' => false,
			'number'     => 2,
		)
	);

	if ( is_wp_error( $found ) || empty( $found ) ) {
		return new WP_Error(
			'imperal_seo_not_found',
			__( 'No term with that slug.', 'imperal-seo-bridge' ),
			array( 'status' => 404 )
		);
	}

	if ( count( $found ) > 1 ) {
		return new WP_Error(
			'imperal_seo_ambiguous_slug',
			__( 'That slug matches more than one term — pass the numeric id, or the taxonomy.', 'imperal-seo-bridge' ),
			array( 'status' => 409 )
		);
	}

	return $found[0];
}

/**
 * Permission callback for the term routes.
 *
 * @param WP_REST_Request $request Request.
 * @return true|WP_Error
 */
function imperal_seo_bridge_term_permission( $request ) {
	$term = imperal_seo_bridge_resolve_term( $request );

	if ( is_wp_error( $term ) ) {
		return $term;
	}

	if ( ! imperal_seo_bridge_can_edit_term( $term->term_id ) ) {
		return new WP_Error(
			'imperal_seo_forbidden',
			__( 'That WordPress user cannot edit this term.', 'imperal-seo-bridge' ),
			array( 'status' => 403 )
		);
	}

	return true;
}

/**
 * GET handler — return SEO meta for one term.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_seo_bridge_get_term_meta_route( $request ) {
	$term = imperal_seo_bridge_resolve_term( $request );

	if ( is_wp_error( $term ) ) {
		return $term;
	}

	$payload                     = imperal_seo_bridge_term_payload( $term );
	$payload['rank_math_active'] = imperal_seo_bridge_rank_math_active();

	return rest_ensure_response( $payload );
}

/**
 * POST handler — update SEO meta for one term.
 *
 * Only the keys present in the request body are touched, and an explicitly
 * empty value deletes the row rather than storing an empty string — same
 * semantics as the post route.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_seo_bridge_update_term_meta_route( $request ) {
	$term = imperal_seo_bridge_resolve_term( $request );

	if ( is_wp_error( $term ) ) {
		return $term;
	}

	$map = array(
		'meta_title'       => array( 'rank_math_title', 'text' ),
		'meta_description' => array( 'rank_math_description', 'text' ),
		'focus_keyword'    => array( 'rank_math_focus_keyword', 'text' ),
		'canonical_url'    => array( 'rank_math_canonical_url', 'url' ),
		'rich_snippet'     => array( 'rank_math_rich_snippet', 'text' ),
	);

	$changed = array();

	foreach ( $map as $param => $spec ) {
		if ( ! $request->has_param( $param ) ) {
			continue;
		}

		list( $meta_key, $kind ) = $spec;

		$value = imperal_seo_bridge_sanitize( $kind, $request->get_param( $param ) );

		if ( '' === $value ) {
			delete_term_meta( $term->term_id, $meta_key );
		} else {
			update_term_meta( $term->term_id, $meta_key, $value );
		}

		$changed[] = $param;
	}

	if ( $request->has_param( 'robots' ) ) {
		$raw = $request->get_param( 'robots' );

		if ( ! is_array( $raw ) ) {
			return new WP_Error(
				'imperal_seo_invalid_robots',
				__( 'robots must be an array of strings.', 'imperal-seo-bridge' ),
				array( 'status' => 400 )
			);
		}

		$allowed = imperal_seo_bridge_robots_choices();
		$clean   = array();

		foreach ( $raw as $value ) {
			if ( ! is_scalar( $value ) ) {
				continue;
			}
			$value = strtolower( trim( (string) $value ) );
			if ( ! in_array( $value, $allowed, true ) ) {
				return new WP_Error(
					'imperal_seo_invalid_robots',
					sprintf(
						/* translators: 1: rejected value, 2: allowed values */
						__( 'Unknown robots value "%1$s". Allowed: %2$s.', 'imperal-seo-bridge' ),
						$value,
						implode( ', ', $allowed )
					),
					array( 'status' => 400 )
				);
			}
			$clean[] = $value;
		}

		$clean = array_values( array_unique( $clean ) );

		if ( empty( $clean ) ) {
			delete_term_meta( $term->term_id, 'rank_math_robots' );
		} else {
			update_term_meta( $term->term_id, 'rank_math_robots', $clean );
		}

		$changed[] = 'robots';
	}

	if ( empty( $changed ) ) {
		return new WP_Error(
			'imperal_seo_nothing_to_update',
			__( 'No SEO fields were supplied.', 'imperal-seo-bridge' ),
			array( 'status' => 400 )
		);
	}

	$payload                     = imperal_seo_bridge_term_payload( $term );
	$payload['rank_math_active'] = imperal_seo_bridge_rank_math_active();
	$payload['updated_fields']   = $changed;

	return rest_ensure_response( $payload );
}

/**
 * Permission callback for reading SEO meta.
 *
 * @param WP_REST_Request $request Request.
 * @return true|WP_Error
 */
function imperal_seo_bridge_read_permission( $request ) {
	$post = imperal_seo_bridge_resolve_post( $request );

	if ( is_wp_error( $post ) ) {
		return $post;
	}

	if ( ! current_user_can( 'edit_post', $post->ID ) ) {
		return new WP_Error(
			'imperal_seo_forbidden',
			__( 'That WordPress user cannot edit this item.', 'imperal-seo-bridge' ),
			array( 'status' => 403 )
		);
	}

	return true;
}

/**
 * GET handler — return SEO meta for one post.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_seo_bridge_get_meta( $request ) {
	$post = imperal_seo_bridge_resolve_post( $request );

	if ( is_wp_error( $post ) ) {
		return $post;
	}

	$payload                    = imperal_seo_bridge_payload( $post );
	$payload['rank_math_active'] = imperal_seo_bridge_rank_math_active();

	return rest_ensure_response( $payload );
}

/**
 * POST handler — update SEO meta for one post.
 *
 * Only the keys actually present in the request body are touched, so a caller
 * can update the description without wiping the title.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_seo_bridge_update_meta( $request ) {
	$post = imperal_seo_bridge_resolve_post( $request );

	if ( is_wp_error( $post ) ) {
		return $post;
	}

	$map = array(
		'meta_title'       => array( 'rank_math_title', 'text' ),
		'meta_description' => array( 'rank_math_description', 'text' ),
		'focus_keyword'    => array( 'rank_math_focus_keyword', 'text' ),
		'canonical_url'    => array( 'rank_math_canonical_url', 'url' ),
		'rich_snippet'     => array( 'rank_math_rich_snippet', 'text' ),
	);

	$changed = array();

	foreach ( $map as $param => $spec ) {
		if ( ! $request->has_param( $param ) ) {
			continue;
		}

		list( $meta_key, $kind ) = $spec;

		$value = imperal_seo_bridge_sanitize( $kind, $request->get_param( $param ) );

		if ( '' === $value ) {
			delete_post_meta( $post->ID, $meta_key );
		} else {
			update_post_meta( $post->ID, $meta_key, $value );
		}

		$changed[] = $param;
	}

	if ( $request->has_param( 'robots' ) ) {
		$raw = $request->get_param( 'robots' );

		if ( ! is_array( $raw ) ) {
			return new WP_Error(
				'imperal_seo_invalid_robots',
				__( 'robots must be an array of strings.', 'imperal-seo-bridge' ),
				array( 'status' => 400 )
			);
		}

		$allowed = imperal_seo_bridge_robots_choices();
		$clean   = array();

		foreach ( $raw as $value ) {
			if ( ! is_scalar( $value ) ) {
				continue;
			}
			$value = strtolower( trim( (string) $value ) );
			if ( ! in_array( $value, $allowed, true ) ) {
				return new WP_Error(
					'imperal_seo_invalid_robots',
					sprintf(
						/* translators: 1: rejected value, 2: allowed values */
						__( 'Unknown robots value "%1$s". Allowed: %2$s.', 'imperal-seo-bridge' ),
						$value,
						implode( ', ', $allowed )
					),
					array( 'status' => 400 )
				);
			}
			$clean[] = $value;
		}

		$clean = array_values( array_unique( $clean ) );

		if ( empty( $clean ) ) {
			delete_post_meta( $post->ID, 'rank_math_robots' );
		} else {
			update_post_meta( $post->ID, 'rank_math_robots', $clean );
		}

		$changed[] = 'robots';
	}

	if ( empty( $changed ) ) {
		return new WP_Error(
			'imperal_seo_nothing_to_update',
			__( 'No SEO fields were supplied.', 'imperal-seo-bridge' ),
			array( 'status' => 400 )
		);
	}

	$payload                     = imperal_seo_bridge_payload( get_post( $post->ID ) );
	$payload['updated']          = $changed;
	$payload['rank_math_active'] = imperal_seo_bridge_rank_math_active();

	return rest_ensure_response( $payload );
}

/**
 * Is Rank Math actually installed and running?
 *
 * @return bool
 */
function imperal_seo_bridge_rank_math_active() {
	return defined( 'RANK_MATH_VERSION' ) || class_exists( 'RankMath' );
}

/**
 * GET /status — lets the connector detect the bridge and Rank Math.
 *
 * Deliberately readable by any authenticated user who can edit content, so the
 * connector can report "plugin missing" vs "Rank Math missing" precisely.
 *
 * @return WP_REST_Response
 */
function imperal_seo_bridge_status() {
	return rest_ensure_response(
		array(
			'bridge'            => true,
			'bridge_version'    => IMPERAL_SEO_BRIDGE_VERSION,
			'rank_math_active'  => imperal_seo_bridge_rank_math_active(),
			'rank_math_version' => defined( 'RANK_MATH_VERSION' ) ? RANK_MATH_VERSION : '',
			'post_types'        => imperal_seo_bridge_post_types(),
			'taxonomies'        => imperal_seo_bridge_taxonomies(),
			'robots_choices'    => imperal_seo_bridge_robots_choices(),
		)
	);
}

/**
 * Register the REST routes.
 */
/**
 * Forbid every cache layer from storing this namespace's responses.
 *
 * These routes are permission-gated and their bodies differ per user, so a
 * page cache that stores one response and replays it is an access-control
 * failure, not just staleness. Observed live: LiteSpeed returned
 * `x-litespeed-cache: hit` and served an authenticated SEO payload to an
 * anonymous caller, while the same request with a cache-buster correctly
 * returned 403. It also made a read straight after a write look empty.
 *
 * Hooked on rest_pre_dispatch so it runs before the handler, and scoped to
 * this namespace so caching elsewhere on the site is left alone.
 *
 * @param mixed           $result  Unused; returned untouched.
 * @param WP_REST_Server  $server  Unused.
 * @param WP_REST_Request $request Current request.
 * @return mixed The untouched $result.
 */
function imperal_seo_bridge_no_cache( $result, $server, $request ) {
	if ( ! $request instanceof WP_REST_Request ) {
		return $result;
	}

	if ( 0 !== strpos( ltrim( $request->get_route(), '/' ), IMPERAL_SEO_BRIDGE_NAMESPACE ) ) {
		return $result;
	}

	// Honoured by LiteSpeed, WP Super Cache, W3 Total Cache and others.
	if ( ! defined( 'DONOTCACHEPAGE' ) ) {
		define( 'DONOTCACHEPAGE', true );
	}

	// LiteSpeed's own switch — the plugin that was caching us in practice.
	do_action( 'litespeed_control_set_nocache', 'Imperal SEO Bridge: per-user data' );

	nocache_headers();

	if ( ! headers_sent() ) {
		header( 'Cache-Control: no-store, no-cache, must-revalidate, max-age=0, private', true );
		header( 'X-LiteSpeed-Cache-Control: no-cache', true );
	}

	return $result;
}
add_filter( 'rest_pre_dispatch', 'imperal_seo_bridge_no_cache', 10, 3 );

function imperal_seo_bridge_register_routes() {
	$target_args = array(
		'id'   => array(
			'type'        => 'integer',
			'required'    => false,
			'description' => 'Numeric post or page id.',
		),
		'slug' => array(
			'type'        => 'string',
			'required'    => false,
			'description' => 'Post or page slug, used when no id is given.',
		),
		'type' => array(
			'type'        => 'string',
			'required'    => false,
			'description' => 'Optional post type to disambiguate a slug.',
		),
	);

	register_rest_route(
		IMPERAL_SEO_BRIDGE_NAMESPACE,
		'/seo',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_seo_bridge_get_meta',
				'permission_callback' => 'imperal_seo_bridge_read_permission',
				'args'                => $target_args,
			),
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_seo_bridge_update_meta',
				'permission_callback' => 'imperal_seo_bridge_read_permission',
				'args'                => $target_args,
			),
		)
	);

	$term_args = array(
		'id'       => array(
			'type'        => 'integer',
			'required'    => false,
			'description' => 'Numeric term id.',
		),
		'slug'     => array(
			'type'        => 'string',
			'required'    => false,
			'description' => 'Term slug, used when no id is given.',
		),
		'taxonomy' => array(
			'type'        => 'string',
			'required'    => false,
			'description' => 'Optional taxonomy to disambiguate a slug.',
		),
		'type'     => array(
			'type'        => 'string',
			'required'    => false,
			'description' => 'Alias of taxonomy, for callers reusing the post arg name.',
		),
	);

	register_rest_route(
		IMPERAL_SEO_BRIDGE_NAMESPACE,
		'/seo/term',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_seo_bridge_get_term_meta_route',
				'permission_callback' => 'imperal_seo_bridge_term_permission',
				'args'                => $term_args,
			),
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_seo_bridge_update_term_meta_route',
				'permission_callback' => 'imperal_seo_bridge_term_permission',
				'args'                => $term_args,
			),
		)
	);

	register_rest_route(
		IMPERAL_SEO_BRIDGE_NAMESPACE,
		'/seo/status',
		array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => 'imperal_seo_bridge_status',
			'permission_callback' => function () {
				return current_user_can( 'edit_posts' );
			},
		)
	);
}
add_action( 'rest_api_init', 'imperal_seo_bridge_register_routes' );

<?php
/**
 * Plugin Name:       Imperal Bridge
 * Plugin URI:        https://panel.imperal.io
 * Description:       The single companion plugin for Imperal / Webbee — exposes Rank Math SEO fields, Elementor/Bricks page-builder content, external-image sideloading, server diagnostics (WP/PHP versions, plugin/theme/core updates, cron count, DB size), and Rank Math's site-wide data (SEO score, robots.txt editor, sitemap module status, 404 monitor log) to the WordPress REST API, all under one plugin. Everything Imperal's WordPress Hub connector needs from a WordPress site that stock REST + an Application Password cannot already provide.
 * Version:           2.9.0
 * Requires at least: 6.0
 * Requires PHP:      8.0
 * Author:            Imperal Cloud
 * Author URI:        https://imperal.io
 * License:           GPL v2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       imperal-bridge
 *
 * ---------------------------------------------------------------------------
 * WHY THIS PLUGIN EXISTS — AND WHY IT IS ONE PLUGIN, NOT THREE
 *
 * WordPress core only exposes post meta over the REST API when it is
 * registered with show_in_rest. Rank Math never calls register_post_meta()/
 * register_meta() for its own rank_math_* keys (verified against
 * seo-by-rank-math 1.0.274.1), and neither Elementor nor Bricks do it for
 * their page-builder trees either. Without a bridge, all of that data is
 * invisible to the REST API — reads come back empty, writes are silently
 * dropped, and no Application Password can work around it.
 *
 * This plugin used to ship as three separate plugins — Imperal SEO Bridge,
 * Imperal Builder Bridge and Imperal Media Bridge — each solving the same
 * root problem for a different kind of data. They are merged here into ONE
 * plugin on purpose: one thing to install, one thing to update, one version
 * number to check. Every new bridge capability Imperal adds in the future
 * goes into THIS plugin, as a new section below — never into a new plugin.
 * The three original sections (SEO / Builder / Media) are kept intact and
 * clearly marked so each one stays independently auditable.
 *
 * All routes still live under the same `imperal/v1` REST namespace they always
 * did, with the same route paths (`/seo`, `/seo/term`, `/seo/status`,
 * `/builder`, `/builder/field`, `/builder/status`, `/builder/scan`,
 * `/media/sideload`, `/media/status`) plus one new `/status` endpoint that
 * reports on the plugin as a whole. Sites that already had the three
 * individual bridges installed can deactivate/delete those and install this
 * one instead — no endpoint moves, nothing else on the site changes.
 * ---------------------------------------------------------------------------
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'IMPERAL_BRIDGE_VERSION', '2.9.0' );
define( 'IMPERAL_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * GET /imperal/v1/status — single capability-discovery endpoint for the
 * whole plugin (all three sections at once), so the connector can confirm
 * "Imperal Bridge is installed and at version X" with one call instead of
 * three. The per-section /seo/status, /builder/status and /media/status
 * endpoints below are kept as-is for existing callers.
 *
 * @return WP_REST_Response
 */
function imperal_bridge_status() {
	return rest_ensure_response(
		array(
			'bridge'         => true,
			'bridge_version' => IMPERAL_BRIDGE_VERSION,
			'sections'       => array( 'seo', 'builder', 'media', 'server', 'redirects', 'users', 'rankmath', 'llmstxt', 'meta', 'security', 'deploy', 'database', 'logs' ),
		)
	);
}

add_action(
	'rest_api_init',
	function () {
		register_rest_route(
			IMPERAL_BRIDGE_NAMESPACE,
			'/status',
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_bridge_status',
				'permission_callback' => function () {
					return current_user_can( 'edit_posts' );
				},
			)
		);
	}
);

/* =============================================================================
 * SECTION 1 — SEO (formerly the standalone "Imperal SEO Bridge" plugin)
 *
 * Exposes Rank Math SEO fields (title, description, focus keyword, robots,
 * canonical, schema/rich-snippet type) for posts, pages, CPTs and taxonomy
 * terms (categories, tags).
 *
 * Kept its own version/namespace constants (same names as when it shipped
 * standalone) so nothing inside this section had to be touched during the
 * merge — only the plugin header and file layout changed.
 * ============================================================================= */

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

/* =============================================================================
 * SECTION 2 — BUILDER (formerly the standalone "Imperal Builder Bridge" plugin)
 *
 * Exposes Elementor and Bricks page-builder element trees, with guarded
 * single-field point edits, so Imperal / Webbee can read and precisely edit
 * builder content without touching the rest of the page.
 * ============================================================================= */

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

/* =============================================================================
 * SECTION 3 — MEDIA (formerly the standalone "Imperal Media Bridge" plugin)
 *
 * Lets Imperal / Webbee add an existing public image URL to the WordPress
 * media library and attach it to a post as featured or inline media, without
 * ever routing image bytes through the Imperal platform's own HTTP client.
 * ============================================================================= */

define( 'IMPERAL_MEDIA_BRIDGE_VERSION', '1.1.0' );
define( 'IMPERAL_MEDIA_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * Recognised image extensions the bridge will trust straight off the
 * source_url's own path. Anything else (no extension, a signed CDN path
 * with no file suffix, an unrecognised one) falls back to 'jpg' -- every
 * provider this bridge has seen (Magnific/Freepik, Imagen4, Gemini) serves
 * actual JPEG/PNG bytes regardless of what its URL path looks like, so this
 * is a safe, simple default rather than inspecting the downloaded bytes.
 *
 * @param string $url Raw source_url.
 * @return string Lowercase extension, no leading dot.
 */
function imperal_media_bridge_extension_from_url( $url ) {
	$path = wp_parse_url( $url, PHP_URL_PATH );
	if ( ! $path ) {
		return 'jpg';
	}
	$ext = strtolower( pathinfo( $path, PATHINFO_EXTENSION ) );
	$allowed = array( 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tif', 'tiff' );
	return in_array( $ext, $allowed, true ) ? $ext : 'jpg';
}

/**
 * Build the actual file name this attachment will be saved under.
 *
 * When the caller supplies `filename` (Media Hub's SEO/AEO-optimized slug,
 * e.g. "heat-recovery-ventilator-featured"), THAT -- not the source_url's own
 * path -- becomes the on-disk/on-site file name. This is the fix for images
 * landing on a site as an opaque provider id like
 * "result_IMAGEN4_ULTRA_f992763b....png": the caller now controls the name
 * end to end instead of inheriting whatever the image-generation provider's
 * CDN URL happened to be.
 *
 * @param string $filename_param Sanitized `filename` request param, no extension.
 * @param string $source_url     Original source_url, used only for the extension
 *                                and as the whole-name fallback when filename_param is empty.
 * @return string A safe WordPress file name, WITH extension.
 */
function imperal_media_bridge_target_filename( $filename_param, $source_url ) {
	$ext = imperal_media_bridge_extension_from_url( $source_url );
	if ( '' !== $filename_param ) {
		return $filename_param . '.' . $ext;
	}
	$path = wp_parse_url( $source_url, PHP_URL_PATH );
	$base = $path ? basename( $path ) : '';
	return '' !== $base ? $base : ( 'image.' . $ext );
}


/**
 * Reject obviously private/loopback/link-local hosts. Best-effort string
 * check on the hostname as given — not a DNS-resolution-time guarantee,
 * but it stops the common "http://localhost/..." and raw-IP mistakes.
 *
 * @param string $host Hostname from the parsed URL.
 * @return bool True if the host looks private/internal.
 */
function imperal_media_bridge_is_private_host( $host ) {
	$host = strtolower( trim( $host ) );

	if ( '' === $host || 'localhost' === $host ) {
		return true;
	}

	// IPv4 literal — check the well-known private/loopback/link-local blocks.
	if ( preg_match( '/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/', $host, $m ) ) {
		$a = (int) $m[1];
		$b = (int) $m[2];
		if ( 127 === $a || 10 === $a || 0 === $a ) {
			return true;
		}
		if ( 172 === $a && $b >= 16 && $b <= 31 ) {
			return true;
		}
		if ( 192 === $a && 168 === $b ) {
			return true;
		}
		if ( 169 === $a && 254 === $b ) { // link-local
			return true;
		}
		return false;
	}

	// IPv6 loopback / unique-local literals.
	if ( '::1' === $host || 0 === strpos( $host, 'fc' ) || 0 === strpos( $host, 'fd' ) ) {
		return true;
	}

	return false;
}

/**
 * Validate the source_url argument: must be a well-formed https:// URL
 * pointing at a public host.
 *
 * @param string $url Raw source_url from the request.
 * @return WP_Error|null Error, or null when valid.
 */
function imperal_media_bridge_validate_source_url( $url ) {
	$parts = wp_parse_url( (string) $url );

	if ( ! is_array( $parts ) || empty( $parts['scheme'] ) || empty( $parts['host'] ) ) {
		return new WP_Error(
			'imperal_media_invalid_url',
			__( 'source_url must be a well-formed URL.', 'imperal-media-bridge' ),
			array( 'status' => 400 )
		);
	}

	if ( 'https' !== strtolower( $parts['scheme'] ) ) {
		return new WP_Error(
			'imperal_media_insecure_url',
			__( 'source_url must use https://.', 'imperal-media-bridge' ),
			array( 'status' => 400 )
		);
	}

	if ( imperal_media_bridge_is_private_host( $parts['host'] ) ) {
		return new WP_Error(
			'imperal_media_private_host',
			__( 'source_url must point at a public host.', 'imperal-media-bridge' ),
			array( 'status' => 400 )
		);
	}

	return null;
}

/**
 * Resolve a post from id or slug (+optional type) — same contract as the
 * SEO and builder bridges, so all three plugins feel identical from the
 * client side. Returns null (not an error) when no target was given at all,
 * since attaching to a post is optional for this endpoint.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_Post|WP_Error|null
 */
function imperal_media_bridge_resolve_post( $request ) {
	$id   = (int) $request->get_param( 'post_id' );
	$slug = (string) $request->get_param( 'post_slug' );
	$type = (string) $request->get_param( 'post_type' );

	if ( 0 === $id && '' === trim( $slug ) ) {
		return null;
	}

	if ( $id > 0 ) {
		$post = get_post( $id );
		if ( ! $post instanceof WP_Post ) {
			return new WP_Error(
				'imperal_media_post_not_found',
				__( 'No post or page with that id.', 'imperal-media-bridge' ),
				array( 'status' => 404 )
			);
		}
		return $post;
	}

	$args = array(
		'name'        => sanitize_title( $slug ),
		'post_status' => array( 'publish', 'draft', 'pending', 'private', 'future' ),
		'numberposts' => 2,
	);
	$args['post_type'] = '' !== trim( $type ) ? sanitize_key( $type ) : 'any';

	$found = get_posts( $args );

	if ( empty( $found ) ) {
		return new WP_Error(
			'imperal_media_post_not_found',
			__( 'No post or page with that slug.', 'imperal-media-bridge' ),
			array( 'status' => 404 )
		);
	}

	if ( count( $found ) > 1 ) {
		return new WP_Error(
			'imperal_media_ambiguous_slug',
			__( 'Several items share that slug — pass post_type to disambiguate.', 'imperal-media-bridge' ),
			array( 'status' => 409 )
		);
	}

	return $found[0];
}

/**
 * Permission check: the acting user must be able to upload files, and — when
 * a target post was given — must also be able to edit that specific post.
 *
 * @param WP_REST_Request $request Request.
 * @return true|WP_Error
 */
function imperal_media_bridge_permission( $request ) {
	if ( ! current_user_can( 'upload_files' ) ) {
		return new WP_Error(
			'imperal_media_forbidden',
			__( 'This WordPress user cannot upload media.', 'imperal-media-bridge' ),
			array( 'status' => 403 )
		);
	}

	$post = imperal_media_bridge_resolve_post( $request );
	if ( is_wp_error( $post ) ) {
		return $post;
	}
	if ( $post instanceof WP_Post && ! current_user_can( 'edit_post', $post->ID ) ) {
		return new WP_Error(
			'imperal_media_forbidden',
			__( 'This WordPress user cannot edit that post.', 'imperal-media-bridge' ),
			array( 'status' => 403 )
		);
	}

	return true;
}

/**
 * POST /imperal/v1/media/sideload — fetch a public HTTPS image URL server-side
 * and register it as a media library attachment, optionally attaching it to
 * a post as the featured image.
 *
 * WHY download_url()+media_handle_sideload() INSTEAD OF media_sideload_image().
 * media_sideload_image() derives the saved file's name from source_url itself
 * (WordPress's internal parse of the URL's last path segment) -- there is no
 * parameter to override it. For an image-generation provider whose URL is an
 * opaque signed id (e.g. ".../result_IMAGEN4_ULTRA_f992763b....png"), that
 * meant every image landing on a real site kept that meaningless name
 * forever -- bad for on-site SEO and for AEO/answer engines that read file
 * names as a relevance signal. download_url() fetches to a temp file and
 * media_handle_sideload() accepts an explicit `$file_array['name']`, so the
 * caller's own SEO/AEO slug (Media Hub's `filename` on each asset) becomes
 * the actual saved file name end to end.
 *
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_media_bridge_sideload( $request ) {
	if ( ! function_exists( 'media_handle_sideload' ) ) {
		require_once ABSPATH . 'wp-admin/includes/media.php';
		require_once ABSPATH . 'wp-admin/includes/file.php';
		require_once ABSPATH . 'wp-admin/includes/image.php';
	}

	$source_url = (string) $request->get_param( 'source_url' );
	$url_error  = imperal_media_bridge_validate_source_url( $source_url );
	if ( null !== $url_error ) {
		return $url_error;
	}

	$post        = imperal_media_bridge_resolve_post( $request );
	if ( is_wp_error( $post ) ) {
		return $post;
	}
	$post_id     = $post instanceof WP_Post ? $post->ID : 0;
	$alt_text    = (string) $request->get_param( 'alt_text' );
	$caption     = (string) $request->get_param( 'caption' );
	$as_featured = (bool) $request->get_param( 'set_featured' );
	$filename    = sanitize_file_name( (string) $request->get_param( 'filename' ) );

	$tmp_file = download_url( $source_url );
	if ( is_wp_error( $tmp_file ) ) {
		return new WP_Error(
			'imperal_media_sideload_failed',
			sprintf(
				/* translators: %s: underlying WordPress error message. */
				__( 'Could not fetch that image: %s', 'imperal-media-bridge' ),
				$tmp_file->get_error_message()
			),
			array( 'status' => 502 )
		);
	}

	$file_array = array(
		'name'     => imperal_media_bridge_target_filename( $filename, $source_url ),
		'tmp_name' => $tmp_file,
	);

	$attachment_id = media_handle_sideload( $file_array, $post_id, $caption );

	if ( is_wp_error( $attachment_id ) ) {
		wp_delete_file( $tmp_file );
		return new WP_Error(
			'imperal_media_sideload_failed',
			sprintf(
				/* translators: %s: underlying WordPress error message. */
				__( 'Could not fetch that image: %s', 'imperal-media-bridge' ),
				$attachment_id->get_error_message()
			),
			array( 'status' => 502 )
		);
	}

	if ( '' !== trim( $alt_text ) ) {
		update_post_meta( $attachment_id, '_wp_attachment_image_alt', sanitize_text_field( $alt_text ) );
	}

	$featured_set = false;
	if ( $as_featured && $post_id > 0 ) {
		$featured_set = (bool) set_post_thumbnail( $post_id, $attachment_id );
	}

	$src = wp_get_attachment_image_src( $attachment_id, 'full' );

	return rest_ensure_response(
		array(
			'attachment_id' => $attachment_id,
			'url'           => wp_get_attachment_url( $attachment_id ),
			'width'         => is_array( $src ) ? $src[1] : null,
			'height'        => is_array( $src ) ? $src[2] : null,
			'attached_to'   => $post_id > 0 ? $post_id : null,
			'featured_set'  => $featured_set,
		)
	);
}

/**
 * GET /imperal/v1/media/status — capability discovery.
 *
 * @return WP_REST_Response
 */
function imperal_media_bridge_status() {
	return rest_ensure_response(
		array(
			'bridge'         => true,
			'bridge_version' => IMPERAL_MEDIA_BRIDGE_VERSION,
			'can_upload'     => current_user_can( 'upload_files' ),
		)
	);
}

/**
 * Register the REST routes.
 */
function imperal_media_bridge_register_routes() {
	register_rest_route(
		IMPERAL_MEDIA_BRIDGE_NAMESPACE,
		'/media/sideload',
		array(
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_media_bridge_sideload',
				'permission_callback' => 'imperal_media_bridge_permission',
				'args'                => array(
					'source_url'   => array( 'type' => 'string', 'required' => true ),
					'post_id'      => array( 'type' => 'integer' ),
					'post_slug'    => array( 'type' => 'string' ),
					'post_type'    => array( 'type' => 'string' ),
					'alt_text'     => array( 'type' => 'string' ),
					'caption'      => array( 'type' => 'string' ),
					'filename'     => array( 'type' => 'string' ),
					'set_featured' => array( 'type' => 'boolean' ),
				),
			),
		)
	);

	register_rest_route(
		IMPERAL_MEDIA_BRIDGE_NAMESPACE,
		'/media/status',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_media_bridge_status',
				'permission_callback' => function () {
					return current_user_can( 'upload_files' );
				},
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_media_bridge_register_routes' );

/* =============================================================================
 * SECTION 4 — SERVER (WordPress/PHP versions, updates, cron, DB size)
 *
 * Everything here used to require SSH + WP-CLI from the connector side, but
 * every one of these facts (core/PHP version, pending plugin/theme/core
 * updates, cron job count, database size) is plain WordPress core data —
 * get_bloginfo(), PHP_VERSION, get_plugin_updates(), get_theme_updates(),
 * get_core_updates(), the cron option, and one $wpdb query against
 * information_schema. None of it needs a shell. SSH stays available as a
 * fallback for sites that haven't updated this plugin yet, and remains the
 * only path for actions that truly need a shell (installing a plugin).
 * ============================================================================= */

define( 'IMPERAL_SERVER_BRIDGE_NAMESPACE', 'imperal/v1' );
define( 'IMPERAL_SERVER_BRIDGE_VERSION', '1.0.0' );

/**
 * GET /imperal/v1/server/info — WP-CLI-equivalent server diagnostics without
 * a shell: core/PHP version, plugin/theme/core update lists, cron job count,
 * and database size in MB.
 *
 * @return WP_REST_Response
 */
function imperal_server_bridge_info() {
	require_once ABSPATH . 'wp-admin/includes/update.php';
	require_once ABSPATH . 'wp-admin/includes/plugin.php';

	global $wpdb;

	// Plugin updates: get_plugin_updates() returns [plugin_file => object]
	// with ->Name and ->update->new_version.
	$plugin_updates      = get_plugin_updates();
	$plugin_updates_list = array();
	foreach ( $plugin_updates as $file => $data ) {
		$plugin_updates_list[] = array(
			'title'           => isset( $data->Name ) ? $data->Name : $file,
			'version'         => isset( $data->Version ) ? $data->Version : '',
			'update_version'  => isset( $data->update->new_version ) ? $data->update->new_version : '',
		);
	}

	// Theme updates: get_theme_updates() returns [stylesheet => WP_Theme],
	// each with its ->update array (set by core to the transient data --
	// see wp-admin/includes/update.php) carrying 'new_version'.
	$theme_updates      = get_theme_updates();
	$theme_updates_list = array();
	foreach ( $theme_updates as $stylesheet => $theme ) {
		$new_version = '';
		if ( isset( $theme->update ) && is_array( $theme->update )
			&& isset( $theme->update['new_version'] ) ) {
			$new_version = $theme->update['new_version'];
		}
		$theme_updates_list[] = array(
			'title'          => $theme->get( 'Name' ),
			'version'        => $theme->get( 'Version' ),
			'update_version' => $new_version,
		);
	}

	// Core update.
	$core_updates       = get_core_updates();
	$core_update        = false;
	$core_update_version = '';
	if ( is_array( $core_updates ) && ! empty( $core_updates ) ) {
		$first = $core_updates[0];
		if ( isset( $first->response ) && 'upgrade' === $first->response ) {
			$core_update         = true;
			$core_update_version = isset( $first->current ) ? $first->current : '';
		}
	}

	// Cron job count — flatten the cron option's per-timestamp hook arrays.
	$cron_array = _get_cron_array();
	$cron_count = 0;
	if ( is_array( $cron_array ) ) {
		foreach ( $cron_array as $timestamp => $hooks ) {
			if ( ! is_array( $hooks ) ) {
				continue;
			}
			foreach ( $hooks as $hook => $events ) {
				$cron_count += is_array( $events ) ? count( $events ) : 0;
			}
		}
	}

	// Database size in MB — sum data+index length for every table in this DB.
	$db_size_mb = '';
	$row        = $wpdb->get_row(
		$wpdb->prepare(
			"SELECT SUM(data_length + index_length) AS bytes FROM information_schema.tables WHERE table_schema = %s",
			DB_NAME
		)
	);
	if ( $row && null !== $row->bytes ) {
		$db_size_mb = round( ( (float) $row->bytes ) / 1048576, 2 );
	}

	return rest_ensure_response(
		array(
			'bridge'               => true,
			'bridge_version'       => IMPERAL_SERVER_BRIDGE_VERSION,
			'wp_version'           => get_bloginfo( 'version' ),
			'php_version'          => PHP_VERSION,
			'plugin_updates'       => count( $plugin_updates_list ),
			'plugin_updates_list'  => $plugin_updates_list,
			'theme_updates'        => count( $theme_updates_list ),
			'theme_updates_list'   => $theme_updates_list,
			'core_update'          => $core_update,
			'core_update_version'  => $core_update_version,
			'cron_count'           => $cron_count,
			'db_size_mb'           => $db_size_mb,
		)
	);
}

/**
 * Register the REST routes. Gated behind manage_options: this is server-wide
 * diagnostic data (every plugin's update state, DB size), not per-post
 * editing, so it needs an admin-capable WordPress user regardless of which
 * post the acting Application Password could otherwise touch.
 */
function imperal_server_bridge_register_routes() {
	register_rest_route(
		IMPERAL_SERVER_BRIDGE_NAMESPACE,
		'/server/info',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_server_bridge_info',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_server_bridge_register_routes' );

/* =============================================================================
 * SECTION 5 — REDIRECTS (Rank Math's URL redirection module)
 *
 * Rank Math never registers its own REST routes for the Redirections module
 * (verified against seo-by-rank-math 1.0.274.1 — the admin UI talks to
 * admin-ajax.php, not the REST API), so without a bridge this data is
 * completely invisible to Imperal, the same problem SECTION 1 solves for
 * per-post SEO meta. Redirects live in Rank Math's own custom table
 * ({$wpdb->prefix}rank_math_redirections: id, sources, url_to, header_code,
 * hits, status, created, updated, last_accessed) rather than wp_postmeta, so
 * this section talks to that table directly via $wpdb rather than any WP
 * core object API. `sources` is a serialized array of
 * {pattern, comparison} pairs — Rank Math's own storage shape, preserved
 * here rather than reinvented. A companion cache table
 * ({$wpdb->prefix}rank_math_redirections_cache) memoises URL → redirection
 * matches for speed; it is purely a rebuildable performance cache (Rank
 * Math repopulates it lazily on the next unmatched request), so this
 * section simply clears it after any write rather than depending on
 * internal Rank Math cache-invalidation classes that may not be loaded.
 * ============================================================================= */

define( 'IMPERAL_REDIRECTS_BRIDGE_NAMESPACE', 'imperal/v1' );
define( 'IMPERAL_REDIRECTS_BRIDGE_VERSION', '1.0.0' );

/**
 * Whether Rank Math's redirections table exists on this site (module may be
 * disabled, or Rank Math itself may not be installed).
 *
 * @return bool
 */
function imperal_redirects_bridge_table_exists() {
	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_redirections';
	$found = $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) );
	return $found === $table;
}

/**
 * Format one redirections table row for the REST response.
 *
 * @param object $row Raw $wpdb row.
 * @return array
 */
function imperal_redirects_bridge_format_row( $row ) {
	$sources = maybe_unserialize( $row->sources );
	if ( ! is_array( $sources ) ) {
		$sources = array();
	}
	return array(
		'id'            => (int) $row->id,
		'sources'       => $sources,
		'url_to'        => (string) $row->url_to,
		'header_code'   => (int) $row->header_code,
		'hits'          => (int) $row->hits,
		'status'        => (string) $row->status,
		'created'       => (string) $row->created,
		'updated'       => (string) $row->updated,
		'last_accessed' => (string) $row->last_accessed,
	);
}

/**
 * Clear Rank Math's redirection match cache after any write. It is a pure
 * performance cache — Rank Math repopulates it lazily on the next request
 * for a URL it hasn't seen — so truncating it is always safe and avoids a
 * hard dependency on Rank Math's own (private) cache classes.
 */
function imperal_redirects_bridge_clear_cache() {
	global $wpdb;
	$cache_table = $wpdb->prefix . 'rank_math_redirections_cache';
	$found       = $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $cache_table ) );
	if ( $found === $cache_table ) {
		$wpdb->query( "TRUNCATE TABLE {$cache_table}" ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	}
}

/**
 * GET /imperal/v1/redirects — list redirections, optionally filtered by status.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_redirects_bridge_list( $request ) {
	if ( ! imperal_redirects_bridge_table_exists() ) {
		return new WP_Error(
			'imperal_redirects_not_available',
			__( 'Rank Math\'s Redirections module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	global $wpdb;
	$table  = $wpdb->prefix . 'rank_math_redirections';
	$status = $request->get_param( 'status' );

	if ( $status && 'all' !== $status ) {
		$rows = $wpdb->get_results(
			$wpdb->prepare( "SELECT * FROM {$table} WHERE status = %s ORDER BY id DESC", $status ) // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
		);
	} else {
		$rows = $wpdb->get_results( "SELECT * FROM {$table} ORDER BY id DESC" ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	}

	$items = array_map( 'imperal_redirects_bridge_format_row', $rows ? $rows : array() );
	return rest_ensure_response( $items );
}

/**
 * POST /imperal/v1/redirects — create a redirection.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_redirects_bridge_create( $request ) {
	if ( ! imperal_redirects_bridge_table_exists() ) {
		return new WP_Error(
			'imperal_redirects_not_available',
			__( 'Rank Math\'s Redirections module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	$sources = $request->get_param( 'sources' );
	$url_to  = (string) $request->get_param( 'url_to' );
	$code    = (int) $request->get_param( 'header_code' );

	if ( ! is_array( $sources ) || empty( $sources ) || '' === trim( $url_to ) || ! $code ) {
		return new WP_Error(
			'imperal_redirects_invalid',
			__( 'sources (non-empty array), url_to, and header_code are required.', 'imperal-bridge' ),
			array( 'status' => 400 )
		);
	}

	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_redirections';
	$now   = current_time( 'mysql' );

	$wpdb->insert(
		$table,
		array(
			'sources'     => maybe_serialize( $sources ),
			'url_to'      => $url_to,
			'header_code' => $code,
			'hits'        => 0,
			'status'      => 'active',
			'created'     => $now,
			'updated'     => $now,
		),
		array( '%s', '%s', '%d', '%d', '%s', '%s', '%s' )
	);
	$id = (int) $wpdb->insert_id;
	if ( ! $id ) {
		return new WP_Error(
			'imperal_redirects_write_failed',
			__( 'Could not write the redirection.', 'imperal-bridge' ),
			array( 'status' => 500 )
		);
	}
	imperal_redirects_bridge_clear_cache();

	$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	return rest_ensure_response( imperal_redirects_bridge_format_row( $row ) );
}

/**
 * DELETE /imperal/v1/redirects/{id} — permanently delete one redirection.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_redirects_bridge_delete( $request ) {
	if ( ! imperal_redirects_bridge_table_exists() ) {
		return new WP_Error(
			'imperal_redirects_not_available',
			__( 'Rank Math\'s Redirections module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_redirections';
	$id    = (int) $request->get_param( 'id' );

	$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	if ( ! $row ) {
		return new WP_Error(
			'imperal_redirects_not_found',
			__( 'That redirection does not exist.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	$wpdb->delete( $table, array( 'id' => $id ), array( '%d' ) );
	imperal_redirects_bridge_clear_cache();

	return rest_ensure_response( array( 'id' => $id, 'deleted' => true ) );
}

/**
 * POST /imperal/v1/redirects/{id}/status — activate/deactivate/trash a redirection.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_redirects_bridge_set_status( $request ) {
	if ( ! imperal_redirects_bridge_table_exists() ) {
		return new WP_Error(
			'imperal_redirects_not_available',
			__( 'Rank Math\'s Redirections module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	global $wpdb;
	$table  = $wpdb->prefix . 'rank_math_redirections';
	$id     = (int) $request->get_param( 'id' );
	$status = (string) $request->get_param( 'status' );

	if ( ! in_array( $status, array( 'active', 'inactive', 'trashed' ), true ) ) {
		return new WP_Error(
			'imperal_redirects_invalid_status',
			__( 'status must be one of: active, inactive, trashed.', 'imperal-bridge' ),
			array( 'status' => 400 )
		);
	}

	$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	if ( ! $row ) {
		return new WP_Error(
			'imperal_redirects_not_found',
			__( 'That redirection does not exist.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	$wpdb->update(
		$table,
		array( 'status' => $status, 'updated' => current_time( 'mysql' ) ),
		array( 'id' => $id ),
		array( '%s', '%s' ),
		array( '%d' )
	);
	imperal_redirects_bridge_clear_cache();
	$row = $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	return rest_ensure_response( imperal_redirects_bridge_format_row( $row ) );
}

/**
 * Register the redirects REST routes. Gated behind manage_options — Rank
 * Math itself requires 'manage_options' for its Redirections admin screen,
 * so an Application Password without it could never do this from wp-admin
 * either.
 */
function imperal_redirects_bridge_register_routes() {
	register_rest_route(
		IMPERAL_REDIRECTS_BRIDGE_NAMESPACE,
		'/redirects',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_redirects_bridge_list',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_redirects_bridge_create',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
		)
	);
	register_rest_route(
		IMPERAL_REDIRECTS_BRIDGE_NAMESPACE,
		'/redirects/(?P<id>\d+)',
		array(
			'methods'             => WP_REST_Server::DELETABLE,
			'callback'            => 'imperal_redirects_bridge_delete',
			'permission_callback' => function () {
				return current_user_can( 'manage_options' );
			},
		)
	);
	register_rest_route(
		IMPERAL_REDIRECTS_BRIDGE_NAMESPACE,
		'/redirects/(?P<id>\d+)/status',
		array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => 'imperal_redirects_bridge_set_status',
			'permission_callback' => function () {
				return current_user_can( 'manage_options' );
			},
		)
	);
}
add_action( 'rest_api_init', 'imperal_redirects_bridge_register_routes' );

/* =============================================================================
 * SECTION 6 — USERS (password reset)
 *
 * WordPress core has a complete, working password-reset flow -- retrieve_password()
 * validates the user, generates a reset key via get_password_reset_key(), and emails
 * WordPress's own native "click here to reset your password" link via wp_mail(). It is
 * exactly what an admin clicking "Send password reset" in wp-admin's Users list
 * triggers. But it is only ever reachable through wp-login.php?action=lostpassword
 * (a form POST, not a REST route) -- there is no core REST endpoint that calls it.
 * This section is a thin wrapper: one function call, no direct database writes of our
 * own (get_password_reset_key() manages WordPress's own user_activation_key column).
 * ============================================================================= */

define( 'IMPERAL_USERS_BRIDGE_NAMESPACE', 'imperal/v1' );
define( 'IMPERAL_USERS_BRIDGE_VERSION', '1.0.0' );

/**
 * POST /imperal/v1/users/{id}/reset-password — trigger WordPress's own native
 * password-reset email for one user, via core's retrieve_password().
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_users_bridge_reset_password( $request ) {
	$user_id = (int) $request->get_param( 'id' );
	$user    = get_userdata( $user_id );
	if ( ! $user ) {
		return new WP_Error(
			'imperal_users_not_found',
			__( 'That user does not exist.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	require_once ABSPATH . WPINC . '/user.php';
	$result = retrieve_password( $user->user_login );

	if ( is_wp_error( $result ) ) {
		return new WP_Error(
			'imperal_users_reset_failed',
			$result->get_error_message(),
			array( 'status' => 500 )
		);
	}

	return rest_ensure_response(
		array(
			'id'      => $user_id,
			'email'   => $user->user_email,
			'sent'    => true,
		)
	);
}

/**
 * Register the users REST routes. Gated behind edit_users -- the same core
 * capability WordPress itself requires to see the "Send password reset" row
 * action in wp-admin's Users list table.
 */
function imperal_users_bridge_register_routes() {
	register_rest_route(
		IMPERAL_USERS_BRIDGE_NAMESPACE,
		'/users/(?P<id>\d+)/reset-password',
		array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => 'imperal_users_bridge_reset_password',
			'permission_callback' => function () {
				return current_user_can( 'edit_users' );
			},
		)
	);
}
add_action( 'rest_api_init', 'imperal_users_bridge_register_routes' );

/* =============================================================================
 * SECTION 7 — RANK MATH SITE-WIDE (SEO score, robots.txt, sitemap status, 404 log)
 *
 * Four more pieces of Rank Math data that live outside per-post SEO meta
 * (SECTION 1) and outside the Redirections table (SECTION 5), verified
 * against seo-by-rank-math 1.0.275 source before writing a single line here:
 *
 *   - SEO score: a plain integer in postmeta key `rank_math_seo_score`
 *     (RankMath\Frontend_SEO_Score reads it with a bare get_post_meta() call —
 *     no wrapper class, no separate table).
 *   - robots.txt: NOT the raw file on disk. Rank Math's own editor
 *     (RankMath\Robots_Txt) stores the override text in the `robots_txt_content`
 *     key of the `rank-math-options-general` option (one big serialized array —
 *     Rank Math's own settings-storage convention, read/written here via
 *     get_option()/update_option() exactly like Rank Math's own Helper::option()
 *     trait does, never touched with raw SQL since this is a normal WP option).
 *     It only takes effect on a *public* site (Rank Math's own filter checks
 *     $is_public) and only when non-empty — both preserved here.
 *   - Sitemap status: Rank Math generates sitemaps dynamically on request
 *     (RankMath\Sitemap\Router rewrites /sitemap_index.xml et al. at
 *     runtime); there is no stored "last generated" state to read and no
 *     regenerate action to trigger — asking Rank Math to "regenerate" the
 *     sitemap is not a real operation on this plugin, so this section only
 *     reports whether the Sitemap module is active (`rank_math_modules`
 *     option, a plain array of active module ids — RankMath\Helpers\Conditional
 *     ::is_module_active() checks it with a bare in_array()) plus the sitemap
 *     index URL when it is.
 *   - 404 log: read-only view of Rank Math's own 404 Monitor, which logs
 *     real hits in its own table ({$wpdb->prefix}rank_math_404_logs: id, uri,
 *     accessed, times_accessed, referer, user_agent — RankMath\Monitor\DB).
 *     Delete-one-entry is supported (Rank Math's own admin screen offers
 *     the same); bulk-clearing the whole log is deliberately NOT exposed —
 *     no legitimate Imperal workflow needs to wipe 404 history in one call,
 *     and it would remove real diagnostic history with no way back.
 * ============================================================================= */

define( 'IMPERAL_RANKMATH_BRIDGE_NAMESPACE', 'imperal/v1' );
define( 'IMPERAL_RANKMATH_BRIDGE_VERSION', '1.0.0' );

/**
 * GET /imperal/v1/rankmath/score/{id} — read a post's Rank Math SEO score.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_rankmath_bridge_get_score( $request ) {
	$post_id = (int) $request->get_param( 'id' );
	$post    = get_post( $post_id );
	if ( ! $post ) {
		return new WP_Error(
			'imperal_rankmath_post_not_found',
			__( 'That post does not exist.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	$score = get_post_meta( $post_id, 'rank_math_seo_score', true );
	return rest_ensure_response(
		array(
			'id'    => $post_id,
			'score' => '' === $score ? null : (int) $score,
		)
	);
}

/**
 * GET /imperal/v1/rankmath/robots-txt — read Rank Math's robots.txt override text.
 *
 * @return WP_REST_Response
 */
function imperal_rankmath_bridge_get_robots_txt() {
	$general = get_option( 'rank-math-options-general', array() );
	$content = is_array( $general ) ? (string) ( $general['robots_txt_content'] ?? '' ) : '';

	return rest_ensure_response(
		array(
			'content'      => $content,
			'is_active'    => '' !== $content,
			'site_is_public' => (bool) get_option( 'blog_public' ),
		)
	);
}

/**
 * POST /imperal/v1/rankmath/robots-txt — write Rank Math's robots.txt override text.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_rankmath_bridge_update_robots_txt( $request ) {
	$content = $request->get_param( 'content' );
	if ( ! is_string( $content ) ) {
		return new WP_Error(
			'imperal_rankmath_invalid_content',
			__( 'content must be a string (may be empty to clear the override).', 'imperal-bridge' ),
			array( 'status' => 400 )
		);
	}

	$general = get_option( 'rank-math-options-general', array() );
	if ( ! is_array( $general ) ) {
		$general = array();
	}
	$general['robots_txt_content'] = $content;
	update_option( 'rank-math-options-general', $general );

	return rest_ensure_response(
		array(
			'content'   => $content,
			'is_active' => '' !== $content,
		)
	);
}

/**
 * GET /imperal/v1/rankmath/sitemap-status — whether Rank Math's Sitemap
 * module is active, plus the sitemap index URL when it is.
 *
 * @return WP_REST_Response
 */
function imperal_rankmath_bridge_sitemap_status() {
	$active_modules = get_option( 'rank_math_modules', array() );
	$active         = is_array( $active_modules ) && in_array( 'sitemap', $active_modules, true );

	return rest_ensure_response(
		array(
			'module_active' => $active,
			'sitemap_url'   => $active ? home_url( '/sitemap_index.xml' ) : '',
		)
	);
}

/**
 * Whether Rank Math's 404-logs table exists on this site (404 Monitor module
 * may be disabled, or Rank Math itself may not be installed).
 *
 * @return bool
 */
function imperal_rankmath_bridge_404_table_exists() {
	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_404_logs';
	$found = $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) );
	return $found === $table;
}

/**
 * GET /imperal/v1/rankmath/404-logs — list logged 404 hits, newest first.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_rankmath_bridge_list_404_logs( $request ) {
	if ( ! imperal_rankmath_bridge_404_table_exists() ) {
		return new WP_Error(
			'imperal_rankmath_404_not_available',
			__( 'Rank Math\'s 404 Monitor module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_404_logs';
	$limit = min( 100, max( 1, (int) $request->get_param( 'limit' ) ?: 50 ) );

	$rows = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} ORDER BY accessed DESC LIMIT %d", $limit ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared

	$out = array();
	foreach ( (array) $rows as $row ) {
		$out[] = array(
			'id'             => (int) $row->id,
			'uri'            => (string) $row->uri,
			'accessed'       => (string) $row->accessed,
			'times_accessed' => (int) $row->times_accessed,
			'referer'        => (string) $row->referer,
			'user_agent'     => (string) $row->user_agent,
		);
	}

	return rest_ensure_response( $out );
}

/**
 * DELETE /imperal/v1/rankmath/404-logs/{id} — remove one logged 404 hit.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_rankmath_bridge_delete_404_log( $request ) {
	if ( ! imperal_rankmath_bridge_404_table_exists() ) {
		return new WP_Error(
			'imperal_rankmath_404_not_available',
			__( 'Rank Math\'s 404 Monitor module does not appear to be enabled on this site.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	global $wpdb;
	$table = $wpdb->prefix . 'rank_math_404_logs';
	$id    = (int) $request->get_param( 'id' );

	$row = $wpdb->get_row( $wpdb->prepare( "SELECT id FROM {$table} WHERE id = %d", $id ) ); // phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared
	if ( ! $row ) {
		return new WP_Error(
			'imperal_rankmath_404_not_found',
			__( 'That 404 log entry does not exist.', 'imperal-bridge' ),
			array( 'status' => 404 )
		);
	}

	$wpdb->delete( $table, array( 'id' => $id ), array( '%d' ) );

	return rest_ensure_response( array( 'id' => $id, 'deleted' => true ) );
}

/**
 * Register the Rank Math site-wide REST routes. The SEO score read is gated
 * behind edit_posts (matches SECTION 1's own per-post SEO gate — reading a
 * score is no more sensitive than reading a post's SEO meta); robots.txt,
 * sitemap status and the 404 log are gated behind manage_options, matching
 * Rank Math's own admin screens for those (all live under its Settings
 * pages, not the per-post editor).
 */
function imperal_rankmath_bridge_register_routes() {
	register_rest_route(
		IMPERAL_RANKMATH_BRIDGE_NAMESPACE,
		'/rankmath/score/(?P<id>\d+)',
		array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => 'imperal_rankmath_bridge_get_score',
			'permission_callback' => function () {
				return current_user_can( 'edit_posts' );
			},
		)
	);
	register_rest_route(
		IMPERAL_RANKMATH_BRIDGE_NAMESPACE,
		'/rankmath/robots-txt',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_rankmath_bridge_get_robots_txt',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_rankmath_bridge_update_robots_txt',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
		)
	);
	register_rest_route(
		IMPERAL_RANKMATH_BRIDGE_NAMESPACE,
		'/rankmath/sitemap-status',
		array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => 'imperal_rankmath_bridge_sitemap_status',
			'permission_callback' => function () {
				return current_user_can( 'manage_options' );
			},
		)
	);
	register_rest_route(
		IMPERAL_RANKMATH_BRIDGE_NAMESPACE,
		'/rankmath/404-logs',
		array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => 'imperal_rankmath_bridge_list_404_logs',
			'permission_callback' => function () {
				return current_user_can( 'manage_options' );
			},
		)
	);
	register_rest_route(
		IMPERAL_RANKMATH_BRIDGE_NAMESPACE,
		'/rankmath/404-logs/(?P<id>\d+)',
		array(
			'methods'             => WP_REST_Server::DELETABLE,
			'callback'            => 'imperal_rankmath_bridge_delete_404_log',
			'permission_callback' => function () {
				return current_user_can( 'manage_options' );
			},
		)
	);
}
add_action( 'rest_api_init', 'imperal_rankmath_bridge_register_routes' );

/* =============================================================================
 * SECTION 8 — LLMS.TXT (Rank Math's AI-crawler guidance file)
 *
 * Rank Math's llms-txt module (RankMath\LLMS\LLMS_Txt, includes/modules/llms/
 * class-llms-txt.php in seo-by-rank-math trunk, verified before writing this)
 * serves a dynamic, Markdown-format /llms.txt file at the site root via a
 * rewrite rule + template_redirect — the AI-crawler analogue of robots.txt.
 * Its four settings live in the SAME `rank-math-options-general` option that
 * SECTION 7 already reads/writes for robots_txt_content — Rank Math's own
 * settings-storage convention, so this section follows the identical
 * get_option()/update_option() pattern, never raw SQL:
 *
 *   - llms_post_types      (array of post type slugs to list)
 *   - llms_taxonomies      (array of taxonomy slugs to list)
 *   - llms_limit           (int, max links per post type/taxonomy, default 100
 *                           per class-llms-txt.php's output(), 50 per its own
 *                           options.php default field value — the option
 *                           itself has no stored default until first saved)
 *   - llms_extra_content   (string, free-text Markdown appended to the file)
 *
 * Unlike robots.txt, this module is NOT active by default (absent from
 * class-installer.php's create_misc_options() default $modules array) — so
 * this section also reports module_active (from the `rank_math_modules`
 * option, same check SECTION 7 uses for the Sitemap module) and the file's
 * live URL, without inventing an "activate module" action: enabling/
 * disabling Rank Math modules happens on Rank Math's own module-manager
 * screen (a many-module settings UI with no single-module REST toggle in the
 * plugin itself), so this bridge only edits the SETTINGS, matching the
 * boundary already drawn for robots.txt/sitemap in SECTION 7.
 * ============================================================================= */

define( 'IMPERAL_LLMSTXT_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * Is Rank Math's llms-txt module active on this site?
 *
 * @return bool
 */
function imperal_llmstxt_bridge_module_active() {
	$active_modules = get_option( 'rank_math_modules', array() );
	return is_array( $active_modules ) && in_array( 'llms-txt', $active_modules, true );
}

/**
 * GET /imperal/v1/llmstxt — read the llms.txt settings.
 *
 * @return WP_REST_Response
 */
function imperal_llmstxt_bridge_get_settings() {
	$general = get_option( 'rank-math-options-general', array() );
	$general = is_array( $general ) ? $general : array();

	return rest_ensure_response(
		array(
			'module_active'   => imperal_llmstxt_bridge_module_active(),
			'llms_txt_url'    => home_url( '/llms.txt' ),
			'post_types'      => isset( $general['llms_post_types'] ) && is_array( $general['llms_post_types'] )
				? array_values( array_map( 'strval', $general['llms_post_types'] ) ) : array(),
			'taxonomies'      => isset( $general['llms_taxonomies'] ) && is_array( $general['llms_taxonomies'] )
				? array_values( array_map( 'strval', $general['llms_taxonomies'] ) ) : array(),
			'limit'           => isset( $general['llms_limit'] ) ? (int) $general['llms_limit'] : 100,
			'extra_content'   => isset( $general['llms_extra_content'] ) ? (string) $general['llms_extra_content'] : '',
		)
	);
}

/**
 * POST /imperal/v1/llmstxt — update the llms.txt settings. Only keys present
 * in the request body are touched, matching SECTION 7's per-post SEO
 * partial-update convention.
 *
 * @param WP_REST_Request $request Incoming request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_llmstxt_bridge_update_settings( $request ) {
	$general = get_option( 'rank-math-options-general', array() );
	$general = is_array( $general ) ? $general : array();
	$changed = array();

	if ( $request->has_param( 'post_types' ) ) {
		$raw = $request->get_param( 'post_types' );
		if ( ! is_array( $raw ) ) {
			return new WP_Error(
				'imperal_llmstxt_invalid_post_types',
				__( 'post_types must be an array of post type slugs.', 'imperal-bridge' ),
				array( 'status' => 400 )
			);
		}
		$general['llms_post_types'] = array_values( array_map( 'sanitize_key', $raw ) );
		$changed[]                  = 'post_types';
	}

	if ( $request->has_param( 'taxonomies' ) ) {
		$raw = $request->get_param( 'taxonomies' );
		if ( ! is_array( $raw ) ) {
			return new WP_Error(
				'imperal_llmstxt_invalid_taxonomies',
				__( 'taxonomies must be an array of taxonomy slugs.', 'imperal-bridge' ),
				array( 'status' => 400 )
			);
		}
		$general['llms_taxonomies'] = array_values( array_map( 'sanitize_key', $raw ) );
		$changed[]                  = 'taxonomies';
	}

	if ( $request->has_param( 'limit' ) ) {
		$limit = (int) $request->get_param( 'limit' );
		if ( $limit < 1 ) {
			return new WP_Error(
				'imperal_llmstxt_invalid_limit',
				__( 'limit must be a positive integer.', 'imperal-bridge' ),
				array( 'status' => 400 )
			);
		}
		$general['llms_limit'] = $limit;
		$changed[]              = 'limit';
	}

	if ( $request->has_param( 'extra_content' ) ) {
		$extra = $request->get_param( 'extra_content' );
		if ( ! is_string( $extra ) ) {
			return new WP_Error(
				'imperal_llmstxt_invalid_extra_content',
				__( 'extra_content must be a string (may be empty to clear it).', 'imperal-bridge' ),
				array( 'status' => 400 )
			);
		}
		$general['llms_extra_content'] = $extra;
		$changed[]                     = 'extra_content';
	}

	if ( empty( $changed ) ) {
		return new WP_Error(
			'imperal_llmstxt_nothing_to_update',
			__( 'No llms.txt settings were supplied.', 'imperal-bridge' ),
			array( 'status' => 400 )
		);
	}

	update_option( 'rank-math-options-general', $general );

	return rest_ensure_response(
		array(
			'module_active' => imperal_llmstxt_bridge_module_active(),
			'llms_txt_url'  => home_url( '/llms.txt' ),
			'post_types'    => $general['llms_post_types'] ?? array(),
			'taxonomies'    => $general['llms_taxonomies'] ?? array(),
			'limit'         => isset( $general['llms_limit'] ) ? (int) $general['llms_limit'] : 100,
			'extra_content' => $general['llms_extra_content'] ?? '',
			'updated'       => $changed,
		)
	);
}

/**
 * Register the llms.txt REST routes, gated behind manage_options — matches
 * SECTION 7's robots.txt/sitemap gate, since llms.txt settings live under
 * Rank Math's General settings page (an admin-only screen), not the
 * per-post editor.
 */
function imperal_llmstxt_bridge_register_routes() {
	register_rest_route(
		IMPERAL_LLMSTXT_BRIDGE_NAMESPACE,
		'/llmstxt',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_llmstxt_bridge_get_settings',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_llmstxt_bridge_update_settings',
				'permission_callback' => function () {
					return current_user_can( 'manage_options' );
				},
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_llmstxt_bridge_register_routes' );

/* =============================================================================
 * SECTION 9 — GENERIC META (post/user/term meta, wp_options)
 *
 * WordPress core only exposes post meta over the REST API when it is
 * registered with register_post_meta(..., 'show_in_rest' => true). Almost no
 * real-world custom field is registered this way -- ACF fields, raw
 * update_post_meta() calls, and most plugin-added meta are all invisible to
 * /wp/v2/<type>/<id>?context=edit. This section is a generic bridge for
 * exactly that gap: arbitrary meta on posts/users/terms, plus a hard-gated
 * allowlist subset of wp_options.
 *
 * Safety boundary (matches this plugin's existing bar for install_plugin /
 * WP-CLI-equivalent power): wp_options access is an ALLOWLIST of known-safe
 * option names only -- Rank Math's own options, blogname/blogdescription, and
 * a short list of WooCommerce store-settings option names. Never siteurl,
 * home, active_plugins, template, stylesheet, or any option value that looks
 * like a serialized PHP object (a serialized-object payload is refused
 * outright: accepting one could let a caller trigger arbitrary
 * __wakeup()/__destruct() side effects on unserialize() -- a known PHP
 * object-injection risk class, not a hypothetical one).
 * ============================================================================= */

define( 'IMPERAL_META_BRIDGE_NAMESPACE', 'imperal/v1' );
define( 'IMPERAL_META_BRIDGE_VERSION', '1.0.0' );

/**
 * Options this bridge will read/write. Deliberately short and explicit --
 * grow this list only for options that are themselves plain settings
 * arrays/strings, never core identity/security options.
 *
 * @return string[]
 */
function imperal_meta_bridge_option_allowlist() {
	return array(
		'rank-math-options-general',
		'rank-math-options-titles',
		'rank-math-options-sitemap',
		'blogname',
		'blogdescription',
		'woocommerce_store_address',
		'woocommerce_store_address_2',
		'woocommerce_store_city',
		'woocommerce_default_country',
		'woocommerce_store_postcode',
		'woocommerce_currency',
	);
}

/**
 * Reject any value containing a serialized PHP object (O:) token, whether
 * sent as a literal string or nested inside JSON. Plain
 * arrays/strings/numbers/booleans pass.
 *
 * @param mixed $value
 * @return bool true if safe to store
 */
function imperal_meta_bridge_value_is_safe( $value ) {
	$serialized = is_scalar( $value ) ? (string) $value : wp_json_encode( $value );
	if ( false === $serialized ) {
		return false;
	}
	return ! preg_match( '/\bO:\d+:"/', $serialized );
}

function imperal_meta_bridge_get_post_meta( WP_REST_Request $request ) {
	$post_id = (int) $request['id'];
	if ( ! get_post( $post_id ) ) {
		return new WP_Error( 'imperal_meta_no_post', __( 'Post not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = get_post_meta( $post_id );
	$out  = array();
	foreach ( $meta as $key => $values ) {
		$out[ $key ] = 1 === count( $values ) ? maybe_unserialize( $values[0] ) : array_map( 'maybe_unserialize', $values );
	}
	return rest_ensure_response( array( 'post_id' => $post_id, 'meta' => $out ) );
}

function imperal_meta_bridge_update_post_meta( WP_REST_Request $request ) {
	$post_id = (int) $request['id'];
	if ( ! get_post( $post_id ) ) {
		return new WP_Error( 'imperal_meta_no_post', __( 'Post not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = $request->get_param( 'meta' );
	if ( ! is_array( $meta ) || empty( $meta ) ) {
		return new WP_Error( 'imperal_meta_bad_payload', __( 'meta must be a non-empty object of key/value pairs.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	$updated = array();
	foreach ( $meta as $key => $value ) {
		if ( ! imperal_meta_bridge_value_is_safe( $value ) ) {
			return new WP_Error( 'imperal_meta_unsafe_value', sprintf( __( 'Value for "%s" looks like a serialized PHP object and was refused.', 'imperal-bridge' ), $key ), array( 'status' => 400 ) );
		}
		update_post_meta( $post_id, sanitize_key( $key ), $value );
		$updated[] = sanitize_key( $key );
	}
	return rest_ensure_response( array( 'post_id' => $post_id, 'updated' => $updated ) );
}

function imperal_meta_bridge_delete_post_meta( WP_REST_Request $request ) {
	$post_id = (int) $request['id'];
	$key     = sanitize_key( $request['key'] );
	if ( ! get_post( $post_id ) ) {
		return new WP_Error( 'imperal_meta_no_post', __( 'Post not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	delete_post_meta( $post_id, $key );
	return rest_ensure_response( array( 'post_id' => $post_id, 'deleted' => $key ) );
}

function imperal_meta_bridge_get_user_meta( WP_REST_Request $request ) {
	$user_id = (int) $request['id'];
	if ( ! get_userdata( $user_id ) ) {
		return new WP_Error( 'imperal_meta_no_user', __( 'User not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = get_user_meta( $user_id );
	$out  = array();
	foreach ( $meta as $key => $values ) {
		$out[ $key ] = 1 === count( $values ) ? maybe_unserialize( $values[0] ) : array_map( 'maybe_unserialize', $values );
	}
	return rest_ensure_response( array( 'user_id' => $user_id, 'meta' => $out ) );
}

function imperal_meta_bridge_update_user_meta( WP_REST_Request $request ) {
	$user_id = (int) $request['id'];
	if ( ! get_userdata( $user_id ) ) {
		return new WP_Error( 'imperal_meta_no_user', __( 'User not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = $request->get_param( 'meta' );
	if ( ! is_array( $meta ) || empty( $meta ) ) {
		return new WP_Error( 'imperal_meta_bad_payload', __( 'meta must be a non-empty object of key/value pairs.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	$updated = array();
	foreach ( $meta as $key => $value ) {
		if ( ! imperal_meta_bridge_value_is_safe( $value ) ) {
			return new WP_Error( 'imperal_meta_unsafe_value', sprintf( __( 'Value for "%s" looks like a serialized PHP object and was refused.', 'imperal-bridge' ), $key ), array( 'status' => 400 ) );
		}
		update_user_meta( $user_id, sanitize_key( $key ), $value );
		$updated[] = sanitize_key( $key );
	}
	return rest_ensure_response( array( 'user_id' => $user_id, 'updated' => $updated ) );
}

function imperal_meta_bridge_delete_user_meta( WP_REST_Request $request ) {
	$user_id = (int) $request['id'];
	$key     = sanitize_key( $request['key'] );
	if ( ! get_userdata( $user_id ) ) {
		return new WP_Error( 'imperal_meta_no_user', __( 'User not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	delete_user_meta( $user_id, $key );
	return rest_ensure_response( array( 'user_id' => $user_id, 'deleted' => $key ) );
}

function imperal_meta_bridge_get_term_meta( WP_REST_Request $request ) {
	$term_id = (int) $request['id'];
	$term    = get_term( $term_id );
	if ( ! $term || is_wp_error( $term ) ) {
		return new WP_Error( 'imperal_meta_no_term', __( 'Term not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = get_term_meta( $term_id );
	$out  = array();
	foreach ( $meta as $key => $values ) {
		$out[ $key ] = 1 === count( $values ) ? maybe_unserialize( $values[0] ) : array_map( 'maybe_unserialize', $values );
	}
	return rest_ensure_response( array( 'term_id' => $term_id, 'meta' => $out ) );
}

function imperal_meta_bridge_update_term_meta( WP_REST_Request $request ) {
	$term_id = (int) $request['id'];
	$term    = get_term( $term_id );
	if ( ! $term || is_wp_error( $term ) ) {
		return new WP_Error( 'imperal_meta_no_term', __( 'Term not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$meta = $request->get_param( 'meta' );
	if ( ! is_array( $meta ) || empty( $meta ) ) {
		return new WP_Error( 'imperal_meta_bad_payload', __( 'meta must be a non-empty object of key/value pairs.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	$updated = array();
	foreach ( $meta as $key => $value ) {
		if ( ! imperal_meta_bridge_value_is_safe( $value ) ) {
			return new WP_Error( 'imperal_meta_unsafe_value', sprintf( __( 'Value for "%s" looks like a serialized PHP object and was refused.', 'imperal-bridge' ), $key ), array( 'status' => 400 ) );
		}
		update_term_meta( $term_id, sanitize_key( $key ), $value );
		$updated[] = sanitize_key( $key );
	}
	return rest_ensure_response( array( 'term_id' => $term_id, 'updated' => $updated ) );
}

function imperal_meta_bridge_delete_term_meta( WP_REST_Request $request ) {
	$term_id = (int) $request['id'];
	$key     = sanitize_key( $request['key'] );
	$term    = get_term( $term_id );
	if ( ! $term || is_wp_error( $term ) ) {
		return new WP_Error( 'imperal_meta_no_term', __( 'Term not found.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	delete_term_meta( $term_id, $key );
	return rest_ensure_response( array( 'term_id' => $term_id, 'deleted' => $key ) );
}

function imperal_meta_bridge_get_option( WP_REST_Request $request ) {
	$name = sanitize_key( $request['name'] );
	if ( ! in_array( $name, imperal_meta_bridge_option_allowlist(), true ) ) {
		return new WP_Error( 'imperal_meta_option_not_allowed', __( 'This option name is not on the allowed list.', 'imperal-bridge' ), array( 'status' => 403 ) );
	}
	$value = get_option( $name );
	return rest_ensure_response( array( 'name' => $name, 'value' => $value, 'exists' => false !== $value ) );
}

function imperal_meta_bridge_update_option( WP_REST_Request $request ) {
	$name = sanitize_key( $request['name'] );
	if ( ! in_array( $name, imperal_meta_bridge_option_allowlist(), true ) ) {
		return new WP_Error( 'imperal_meta_option_not_allowed', __( 'This option name is not on the allowed list.', 'imperal-bridge' ), array( 'status' => 403 ) );
	}
	$value = $request->get_param( 'value' );
	if ( null === $value ) {
		return new WP_Error( 'imperal_meta_bad_payload', __( 'value is required.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	if ( ! imperal_meta_bridge_value_is_safe( $value ) ) {
		return new WP_Error( 'imperal_meta_unsafe_value', __( 'Value looks like a serialized PHP object and was refused.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	update_option( $name, $value );
	return rest_ensure_response( array( 'name' => $name, 'value' => get_option( $name ) ) );
}

function imperal_meta_bridge_list_acf_fields( WP_REST_Request $request ) {
	if ( ! function_exists( 'acf_get_field_groups' ) ) {
		return new WP_Error( 'imperal_meta_acf_not_active', __( 'Advanced Custom Fields is not active on this site.', 'imperal-bridge' ), array( 'status' => 404 ) );
	}
	$post_type    = sanitize_key( $request->get_param( 'post_type' ) ?: 'post' );
	$field_groups = acf_get_field_groups( array( 'post_type' => $post_type ) );
	$out          = array();
	foreach ( $field_groups as $group ) {
		$fields = function_exists( 'acf_get_fields' ) ? acf_get_fields( $group ) : array();
		$out[]  = array(
			'group_key'   => $group['key'] ?? '',
			'group_title' => $group['title'] ?? '',
			'fields'      => array_map(
				static function ( $field ) {
					return array(
						'key'   => $field['key'] ?? '',
						'name'  => $field['name'] ?? '',
						'label' => $field['label'] ?? '',
						'type'  => $field['type'] ?? '',
					);
				},
				$fields ?: array()
			),
		);
	}
	return rest_ensure_response( array( 'post_type' => $post_type, 'field_groups' => $out ) );
}

function imperal_meta_bridge_register_routes() {
	$manage_options_perm = function () {
		return current_user_can( 'manage_options' );
	};
	$edit_posts_perm     = function () {
		return current_user_can( 'edit_posts' );
	};

	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/postmeta/(?P<id>\d+)',
		array(
			array( 'methods' => WP_REST_Server::READABLE, 'callback' => 'imperal_meta_bridge_get_post_meta', 'permission_callback' => $edit_posts_perm ),
			array( 'methods' => WP_REST_Server::EDITABLE, 'callback' => 'imperal_meta_bridge_update_post_meta', 'permission_callback' => $edit_posts_perm ),
		)
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/postmeta/(?P<id>\d+)/(?P<key>[a-zA-Z0-9_\-]+)',
		array( 'methods' => WP_REST_Server::DELETABLE, 'callback' => 'imperal_meta_bridge_delete_post_meta', 'permission_callback' => $edit_posts_perm )
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/usermeta/(?P<id>\d+)',
		array(
			array( 'methods' => WP_REST_Server::READABLE, 'callback' => 'imperal_meta_bridge_get_user_meta', 'permission_callback' => $manage_options_perm ),
			array( 'methods' => WP_REST_Server::EDITABLE, 'callback' => 'imperal_meta_bridge_update_user_meta', 'permission_callback' => $manage_options_perm ),
		)
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/usermeta/(?P<id>\d+)/(?P<key>[a-zA-Z0-9_\-]+)',
		array( 'methods' => WP_REST_Server::DELETABLE, 'callback' => 'imperal_meta_bridge_delete_user_meta', 'permission_callback' => $manage_options_perm )
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/termmeta/(?P<id>\d+)',
		array(
			array( 'methods' => WP_REST_Server::READABLE, 'callback' => 'imperal_meta_bridge_get_term_meta', 'permission_callback' => $edit_posts_perm ),
			array( 'methods' => WP_REST_Server::EDITABLE, 'callback' => 'imperal_meta_bridge_update_term_meta', 'permission_callback' => $edit_posts_perm ),
		)
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/termmeta/(?P<id>\d+)/(?P<key>[a-zA-Z0-9_\-]+)',
		array( 'methods' => WP_REST_Server::DELETABLE, 'callback' => 'imperal_meta_bridge_delete_term_meta', 'permission_callback' => $edit_posts_perm )
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/option/(?P<name>[a-zA-Z0-9_\-]+)',
		array(
			array( 'methods' => WP_REST_Server::READABLE, 'callback' => 'imperal_meta_bridge_get_option', 'permission_callback' => $manage_options_perm ),
			array( 'methods' => WP_REST_Server::EDITABLE, 'callback' => 'imperal_meta_bridge_update_option', 'permission_callback' => $manage_options_perm ),
		)
	);
	register_rest_route(
		IMPERAL_META_BRIDGE_NAMESPACE,
		'/acf-fields',
		array( 'methods' => WP_REST_Server::READABLE, 'callback' => 'imperal_meta_bridge_list_acf_fields', 'permission_callback' => $edit_posts_perm )
	);
}
add_action( 'rest_api_init', 'imperal_meta_bridge_register_routes' );

/* =============================================================================
 * SECTION 10 — SECURITY / HARDENING DIAGNOSTICS
 *
 * PHP runtime facts (version, loaded extensions, memory/upload/execution
 * limits), the WP_DEBUG/WP_DEBUG_LOG constants, and a basic wp-config.php /
 * wp-content permissions sanity check -- all plain PHP built-ins
 * (phpversion(), get_loaded_extensions(), ini_get(), defined()/constant(),
 * fileperms()) or simple filesystem stat calls. None of it needs a shell.
 * Gated behind manage_options like SECTION 4 (server-wide diagnostic data).
 * ============================================================================= */

define( 'IMPERAL_SECURITY_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * GET /imperal/v1/security/php-info — PHP version, loaded extensions, and
 * the handful of ini limits that gate media uploads / long-running requests.
 */
function imperal_security_bridge_php_info() {
	return rest_ensure_response(
		array(
			'php_version'         => PHP_VERSION,
			'extensions'          => get_loaded_extensions(),
			'memory_limit'        => (string) ini_get( 'memory_limit' ),
			'max_execution_time'  => (string) ini_get( 'max_execution_time' ),
			'upload_max_filesize' => (string) ini_get( 'upload_max_filesize' ),
			'post_max_size'       => (string) ini_get( 'post_max_size' ),
		)
	);
}

/**
 * GET /imperal/v1/security/debug-mode — whether WP_DEBUG / WP_DEBUG_LOG /
 * WP_DEBUG_DISPLAY are on. These should normally be OFF in production;
 * WP_DEBUG_DISPLAY leaking PHP notices/warnings to visitors is a common,
 * genuinely risky misconfiguration.
 */
function imperal_security_bridge_debug_mode() {
	return rest_ensure_response(
		array(
			'wp_debug'         => defined( 'WP_DEBUG' ) && WP_DEBUG,
			'wp_debug_log'     => defined( 'WP_DEBUG_LOG' ) && WP_DEBUG_LOG,
			'wp_debug_display' => defined( 'WP_DEBUG_DISPLAY' ) ? (bool) WP_DEBUG_DISPLAY : true,
		)
	);
}

/**
 * GET /imperal/v1/security/file-permissions — octal permission bits for
 * wp-config.php and the wp-content directory, the two most commonly
 * misconfigured paths (wp-config.php world-readable leaks DB credentials;
 * wp-content writable-by-everyone allows arbitrary file drops). Read-only:
 * this never chmod()s anything, only reports what it finds.
 */
function imperal_security_bridge_file_permissions() {
	$wp_config_path = ABSPATH . 'wp-config.php';
	if ( ! file_exists( $wp_config_path ) ) {
		// wp-config.php can legitimately live one directory above ABSPATH.
		$wp_config_path = dirname( ABSPATH ) . '/wp-config.php';
	}
	$wp_content_path = defined( 'WP_CONTENT_DIR' ) ? WP_CONTENT_DIR : ABSPATH . 'wp-content';

	$perm = function ( $path ) {
		if ( ! file_exists( $path ) ) {
			return null;
		}
		return substr( sprintf( '%o', fileperms( $path ) ), -4 );
	};

	return rest_ensure_response(
		array(
			'wp_config_exists'      => file_exists( $wp_config_path ),
			'wp_config_permissions' => $perm( $wp_config_path ),
			'wp_content_permissions'=> $perm( $wp_content_path ),
		)
	);
}

function imperal_security_bridge_register_routes() {
	$manage_options_perm = function () {
		return current_user_can( 'manage_options' );
	};
	register_rest_route(
		IMPERAL_SECURITY_BRIDGE_NAMESPACE,
		'/security/php-info',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_security_bridge_php_info',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_SECURITY_BRIDGE_NAMESPACE,
		'/security/debug-mode',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_security_bridge_debug_mode',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_SECURITY_BRIDGE_NAMESPACE,
		'/security/file-permissions',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_security_bridge_file_permissions',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_security_bridge_register_routes' );

/* =============================================================================
 * SECTION 11 — DEPLOY / ENVIRONMENT HYGIENE
 *
 * A safe, hard-allowlisted subset of wp-config.php constants (never DB
 * credentials, auth keys or salts), must-use plugins (wp-admin/includes/
 * plugin.php's own get_mu_plugins() -- invisible to list_plugins/
 * list_native_plugins because mu-plugins can't be deactivated and WP core
 * deliberately excludes them from the plugins list), drop-in files
 * (get_dropins(), same file -- object-cache.php/advanced-cache.php/db.php:
 * which caching/DB layer is actually in play), and the environment type
 * WordPress itself declares via wp_get_environment_type() (core since 5.5,
 * wp-includes/load.php). All plain PHP built-ins, no shell needed.
 * ============================================================================= */

define( 'IMPERAL_DEPLOY_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * GET /imperal/v1/deploy/config-constants — a hard-allowlisted subset of
 * wp-config.php constants. NEVER DB_NAME/DB_USER/DB_PASSWORD/DB_HOST, NEVER
 * AUTH_KEY/SECURE_AUTH_KEY/LOGGED_IN_KEY/NONCE_KEY (or their _SALT twins) --
 * those are exactly the secrets a companion plugin must never expose.
 */
function imperal_deploy_bridge_config_constants() {
	global $wp_version, $table_prefix;

	$const_bool_or_null = function ( $name ) {
		return defined( $name ) ? (bool) constant( $name ) : null;
	};
	$const_str_or_null = function ( $name ) {
		return defined( $name ) ? (string) constant( $name ) : null;
	};

	return rest_ensure_response(
		array(
			'wp_version'          => isset( $wp_version ) ? $wp_version : get_bloginfo( 'version' ),
			'table_prefix'        => isset( $table_prefix ) ? $table_prefix : '',
			'wp_debug'            => $const_bool_or_null( 'WP_DEBUG' ),
			'wp_cache'            => $const_bool_or_null( 'WP_CACHE' ),
			'wp_environment_type' => $const_str_or_null( 'WP_ENVIRONMENT_TYPE' ),
			'wp_home'             => $const_str_or_null( 'WP_HOME' ),
			'wp_siteurl'          => $const_str_or_null( 'WP_SITEURL' ),
			'disallow_file_edit'  => $const_bool_or_null( 'DISALLOW_FILE_EDIT' ),
			'disallow_file_mods'  => $const_bool_or_null( 'DISALLOW_FILE_MODS' ),
			'automatic_updater_disabled' => $const_bool_or_null( 'AUTOMATIC_UPDATER_DISABLED' ),
		)
	);
}

/**
 * GET /imperal/v1/deploy/mu-plugins — must-use plugins, invisible to
 * list_plugins/list_native_plugins (they can't be deactivated, so WP core
 * deliberately excludes them from the regular plugins list).
 */
function imperal_deploy_bridge_mu_plugins() {
	require_once ABSPATH . 'wp-admin/includes/plugin.php';
	$mu = get_mu_plugins();
	$out = array();
	foreach ( $mu as $file => $data ) {
		$out[] = array(
			'file'        => $file,
			'name'        => isset( $data['Name'] ) ? $data['Name'] : $file,
			'version'     => isset( $data['Version'] ) ? $data['Version'] : '',
			'description' => isset( $data['Description'] ) ? $data['Description'] : '',
		);
	}
	return rest_ensure_response( $out );
}

/**
 * GET /imperal/v1/deploy/drop-ins — WP core drop-in files
 * (object-cache.php, advanced-cache.php, db.php, etc.) that are actually
 * present in wp-content, with their reported Name/Description so it's
 * clear WHICH caching/DB plugin dropped each one in.
 */
function imperal_deploy_bridge_drop_ins() {
	require_once ABSPATH . 'wp-admin/includes/plugin.php';
	$dropins = get_dropins();
	$out = array();
	foreach ( $dropins as $file => $data ) {
		$out[] = array(
			'file'        => $file,
			'name'        => isset( $data['Name'] ) ? $data['Name'] : $file,
			'description' => isset( $data['Description'] ) ? $data['Description'] : '',
		);
	}
	return rest_ensure_response( $out );
}

/**
 * GET /imperal/v1/deploy/environment-type — WordPress 5.5+'s own
 * wp_get_environment_type(): local / development / staging / production
 * (defaults to 'production' if the site never declared one).
 */
function imperal_deploy_bridge_environment_type() {
	return rest_ensure_response(
		array(
			'environment_type' => function_exists( 'wp_get_environment_type' )
				? wp_get_environment_type()
				: 'production',
		)
	);
}

function imperal_deploy_bridge_register_routes() {
	$manage_options_perm = function () {
		return current_user_can( 'manage_options' );
	};
	register_rest_route(
		IMPERAL_DEPLOY_BRIDGE_NAMESPACE,
		'/deploy/config-constants',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_deploy_bridge_config_constants',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DEPLOY_BRIDGE_NAMESPACE,
		'/deploy/mu-plugins',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_deploy_bridge_mu_plugins',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DEPLOY_BRIDGE_NAMESPACE,
		'/deploy/drop-ins',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_deploy_bridge_drop_ins',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DEPLOY_BRIDGE_NAMESPACE,
		'/deploy/environment-type',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_deploy_bridge_environment_type',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_deploy_bridge_register_routes' );

/* =============================================================================
 * SECTION 12 — DATABASE (search-replace migration, table maintenance, exports)
 *
 * Every one of these used to require SSH + WP-CLI (`wp search-replace`,
 * `wp db size`, `wp db optimize`, `wp db check`/`repair`, `wp db export`,
 * `wp post list --format=count`) purely because that was the only way this
 * connector could reach the database from OUTSIDE the WordPress process.
 * From inside it, every one of them is a plain $wpdb operation with no shell
 * involved at all -- the same reasoning SECTION 4 already applied to server
 * diagnostics. This section reimplements the same WP-CLI *behaviour*
 * (verified against wp-cli/db-command and wp-cli/entity-command's own PHP
 * source) natively:
 *
 * - search-replace walks every text/blob column of every targeted table,
 *   correctly recursing into PHP-serialized values (arrays/objects encoded
 *   with maybe_serialize()) rather than naively string-replacing the raw
 *   serialized blob, which would corrupt the embedded length prefixes -- the
 *   exact bug class WP-CLI's own recursive replacer exists to avoid. GUID
 *   columns are always skipped, matching `--skip-columns=guid`.
 * - only tables carrying this site's own $wpdb->prefix (or explicitly passed
 *   by the caller, still prefix-checked) are ever touched -- never another
 *   site's tables in a shared-database multisite-style setup.
 * - the preview/apply split from the connector side is preserved server-side
 *   too: this endpoint always takes a `dry_run` flag and NEVER writes when
 *   it's true, so the two-step safety story doesn't rely on trusting the
 *   caller alone.
 * ============================================================================= */

define( 'IMPERAL_DATABASE_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * Every table for THIS site's own $wpdb->prefix -- never another site's
 * tables in a shared database. Matches wp-cli's own table_prefix scoping.
 *
 * @return string[]
 */
function imperal_database_bridge_own_tables() {
	global $wpdb;
	$like  = $wpdb->esc_like( $wpdb->prefix ) . '%';
	$rows  = $wpdb->get_col( $wpdb->prepare( 'SHOW TABLES LIKE %s', $like ) );
	return array_map( 'strval', (array) $rows );
}

/**
 * Validate caller-supplied table names/wildcards against this site's own
 * tables, expanding any '*' wildcard the same way wp-cli's --tables does.
 * Returns null (meaning "every own table") if $requested is empty/null.
 *
 * @param array|null $requested
 * @return array|WP_Error
 */
function imperal_database_bridge_resolve_tables( $requested ) {
	$own = imperal_database_bridge_own_tables();
	if ( empty( $requested ) ) {
		return $own;
	}
	$resolved = array();
	foreach ( (array) $requested as $name ) {
		$name = (string) $name;
		if ( '' === $name || ! preg_match( '/^[A-Za-z0-9_\-\.\*]+$/', $name ) ) {
			return new WP_Error( 'imperal_db_bad_table', sprintf( __( 'Invalid table name or wildcard: %s', 'imperal-bridge' ), $name ), array( 'status' => 400 ) );
		}
		if ( false === strpos( $name, '*' ) ) {
			if ( ! in_array( $name, $own, true ) ) {
				return new WP_Error( 'imperal_db_unknown_table', sprintf( __( 'Table "%s" does not belong to this site.', 'imperal-bridge' ), $name ), array( 'status' => 400 ) );
			}
			$resolved[] = $name;
			continue;
		}
		$pattern = '/^' . str_replace( '\*', '.*', preg_quote( $name, '/' ) ) . '$/';
		foreach ( $own as $table ) {
			if ( preg_match( $pattern, $table ) ) {
				$resolved[] = $table;
			}
		}
	}
	return array_values( array_unique( $resolved ) );
}

/**
 * Recursively replace $old with $new inside a value, correctly re-serializing
 * PHP-serialized arrays/objects rather than naively string-replacing the raw
 * blob (which would desync the embedded length prefixes and corrupt the
 * value). Mirrors wp-cli's own recurse_value() from src/Search_Replace_Command.php.
 *
 * @param mixed  $value
 * @param string $old
 * @param string $new
 * @param int    $count Running replacement count, passed by reference.
 * @return mixed
 */
function imperal_database_bridge_recursive_replace( $value, $old, $new, &$count ) {
	if ( is_array( $value ) ) {
		$out = array();
		foreach ( $value as $k => $v ) {
			$out[ $k ] = imperal_database_bridge_recursive_replace( $v, $old, $new, $count );
		}
		return $out;
	}
	if ( is_object( $value ) ) {
		$out = clone $value;
		foreach ( get_object_vars( $value ) as $k => $v ) {
			$out->$k = imperal_database_bridge_recursive_replace( $v, $old, $new, $count );
		}
		return $out;
	}
	if ( is_string( $value ) ) {
		if ( is_serialized( $value, false ) ) {
			$unserialized = @unserialize( $value ); // phpcs:ignore WordPress.PHP.NoSilencedErrors
			// unserialize() can legitimately return false for a serialized
			// `false` scalar -- only fall through to plain string replace
			// when the string was NOT actually parseable as serialized data.
			if ( false !== $unserialized || 'b:0;' === $value ) {
				$replaced = imperal_database_bridge_recursive_replace( $unserialized, $old, $new, $count );
				return serialize( $replaced );
			}
		}
		$occurrences = substr_count( $value, $old );
		if ( $occurrences > 0 ) {
			$count += $occurrences;
			return str_replace( $old, $new, $value );
		}
		return $value;
	}
	return $value;
}

/**
 * Run (or dry-run) a search-replace across one table's text/blob columns.
 * GUID columns are always skipped, matching wp-cli's --skip-columns=guid.
 *
 * @param string $table
 * @param string $old
 * @param string $new
 * @param bool   $dry_run
 * @return int Replacement count for this table.
 */
function imperal_database_bridge_replace_table( $table, $old, $new, $dry_run ) {
	global $wpdb;

	$columns = $wpdb->get_results( "DESCRIBE `{$table}`" ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	if ( ! $columns ) {
		return 0;
	}

	$primary_key = null;
	$text_cols   = array();
	foreach ( $columns as $col ) {
		if ( 'PRI' === $col->Key && null === $primary_key ) {
			$primary_key = $col->Field;
		}
		if ( 'guid' === $col->Field ) {
			continue;
		}
		if ( preg_match( '/char|text|blob|json/i', $col->Type ) ) {
			$text_cols[] = $col->Field;
		}
	}
	if ( ! $primary_key || empty( $text_cols ) ) {
		return 0;
	}

	$count = 0;
	$page  = 0;
	$size  = 500;
	do {
		$col_list = '`' . $primary_key . '`, `' . implode( '`, `', $text_cols ) . '`';
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		$rows = $wpdb->get_results( $wpdb->prepare( "SELECT {$col_list} FROM `{$table}` LIMIT %d OFFSET %d", $size, $page * $size ), ARRAY_A );
		if ( ! $rows ) {
			break;
		}
		foreach ( $rows as $row ) {
			$pk_value = $row[ $primary_key ];
			$updates  = array();
			foreach ( $text_cols as $col ) {
				$before      = $row[ $col ];
				$row_count   = 0;
				$after       = imperal_database_bridge_recursive_replace( $before, $old, $new, $row_count );
				if ( $row_count > 0 ) {
					$count += $row_count;
					$updates[ $col ] = $after;
				}
			}
			if ( ! $dry_run && ! empty( $updates ) ) {
				$wpdb->update( $table, $updates, array( $primary_key => $pk_value ) ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
			}
		}
		$page++;
	} while ( count( $rows ) === $size );

	return $count;
}

/**
 * POST /imperal/v1/database/search-replace — preview (dry_run=true, default)
 * or execute a search-replace across this site's own tables.
 */
function imperal_database_bridge_search_replace( WP_REST_Request $request ) {
	$old     = (string) $request->get_param( 'old' );
	$new     = (string) $request->get_param( 'new' );
	$dry_run = null === $request->get_param( 'dry_run' ) ? true : (bool) $request->get_param( 'dry_run' );
	$tables  = $request->get_param( 'tables' );

	if ( '' === $old ) {
		return new WP_Error( 'imperal_db_bad_params', __( 'old must not be empty.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}

	$resolved = imperal_database_bridge_resolve_tables( $tables );
	if ( is_wp_error( $resolved ) ) {
		return $resolved;
	}
	if ( empty( $resolved ) ) {
		return new WP_Error( 'imperal_db_no_tables', __( 'No matching tables found for this site.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}

	$total = 0;
	foreach ( $resolved as $table ) {
		$total += imperal_database_bridge_replace_table( $table, $old, $new, $dry_run );
	}

	return rest_ensure_response(
		array(
			'dry_run'      => $dry_run,
			'replacements' => $total,
			'tables'       => $resolved,
		)
	);
}

/**
 * GET /imperal/v1/database/tables — every table for this site's own prefix,
 * with its data+index size in a human-readable form (matches `wp db size --tables`).
 */
function imperal_database_bridge_list_tables() {
	global $wpdb;
	$like = $wpdb->esc_like( $wpdb->prefix ) . '%';
	// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	$rows = $wpdb->get_results(
		$wpdb->prepare(
			"SELECT table_name AS name, (data_length + index_length) AS bytes
			 FROM information_schema.tables
			 WHERE table_schema = %s AND table_name LIKE %s
			 ORDER BY table_name",
			DB_NAME,
			$like
		)
	);
	$out = array();
	foreach ( (array) $rows as $row ) {
		$mb    = round( ( (float) $row->bytes ) / 1048576, 2 );
		$out[] = array( 'name' => $row->name, 'size' => $mb . 'MB' );
	}
	return rest_ensure_response( array( 'tables' => $out ) );
}

/**
 * POST /imperal/v1/database/optimize — `OPTIMIZE TABLE` on every one of this
 * site's own tables (matches `wp db optimize`).
 */
function imperal_database_bridge_optimize() {
	global $wpdb;
	$tables = imperal_database_bridge_own_tables();
	$lines  = array();
	foreach ( $tables as $table ) {
		$row     = $wpdb->get_row( "OPTIMIZE TABLE `{$table}`", ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		$status  = $row['Msg_text'] ?? 'OK';
		$lines[] = "{$table}: {$status}";
	}
	return rest_ensure_response( array( 'output' => implode( "\n", $lines ) ) );
}

/**
 * POST /imperal/v1/database/check — `CHECK TABLE` (repair=false) or
 * `CHECK TABLE` + `REPAIR TABLE` for any damaged table (repair=true) on
 * every one of this site's own tables (matches `wp db check` / `wp db repair`).
 */
function imperal_database_bridge_check( WP_REST_Request $request ) {
	global $wpdb;
	$repair = (bool) $request->get_param( 'repair' );
	$tables = imperal_database_bridge_own_tables();
	$lines  = array();
	foreach ( $tables as $table ) {
		$row    = $wpdb->get_row( "CHECK TABLE `{$table}`", ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		$status = $row['Msg_text'] ?? 'unknown';
		if ( $repair && 'OK' !== $status ) {
			$repair_row = $wpdb->get_row( "REPAIR TABLE `{$table}`", ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
			$status     = 'repaired: ' . ( $repair_row['Msg_text'] ?? 'unknown' );
		}
		$lines[] = "{$table}: {$status}";
	}
	return rest_ensure_response( array( 'output' => implode( "\n", $lines ) ) );
}

/**
 * GET /imperal/v1/database/export — a plain-SQL dump (INSERT statements only,
 * matches `wp db export`'s data) of this site's own tables, capped to keep
 * the REST response bounded. Refuses (400) rather than silently truncating
 * when a table's dump would exceed the cap -- callers should scope `tables`
 * down instead of getting a corrupt partial dump.
 */
function imperal_database_bridge_export( WP_REST_Request $request ) {
	global $wpdb;
	$cap      = 2 * 1024 * 1024; // ~2MB, mirrors the connector's own docstring cap.
	$tables   = $request->get_param( 'tables' );
	$resolved = imperal_database_bridge_resolve_tables( $tables );
	if ( is_wp_error( $resolved ) ) {
		return $resolved;
	}
	if ( empty( $resolved ) ) {
		return new WP_Error( 'imperal_db_no_tables', __( 'No matching tables found for this site.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}

	$sql = '';
	foreach ( $resolved as $table ) {
		$create = $wpdb->get_row( "SHOW CREATE TABLE `{$table}`", ARRAY_N ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		if ( $create && isset( $create[1] ) ) {
			$sql .= $create[1] . ";\n\n";
		}
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
		$rows = $wpdb->get_results( "SELECT * FROM `{$table}`", ARRAY_A );
		foreach ( (array) $rows as $row ) {
			$cols   = '`' . implode( '`, `', array_keys( $row ) ) . '`';
			$quoted = array_map(
				function ( $v ) use ( $wpdb ) {
					return null === $v ? 'NULL' : "'" . $wpdb->_real_escape( $v ) . "'";
				},
				array_values( $row )
			);
			$vals = implode( ', ', $quoted );
			$sql .= "INSERT INTO `{$table}` ({$cols}) VALUES ({$vals});\n";
			if ( strlen( $sql ) > $cap ) {
				return new WP_Error( 'imperal_db_export_too_large', __( 'This export exceeds the size cap — scope `tables` down to fewer tables.', 'imperal-bridge' ), array( 'status' => 400 ) );
			}
		}
		$sql .= "\n";
	}

	return rest_ensure_response( array( 'sql' => $sql, 'size_bytes' => strlen( $sql ) ) );
}

/**
 * GET /imperal/v1/database/post-count?post_type=X — row count for one post
 * type, any status (matches `wp post list --format=count`).
 */
function imperal_database_bridge_post_count( WP_REST_Request $request ) {
	global $wpdb;
	$post_type = sanitize_key( (string) $request->get_param( 'post_type' ) );
	if ( '' === $post_type ) {
		return new WP_Error( 'imperal_db_bad_params', __( 'post_type must not be empty.', 'imperal-bridge' ), array( 'status' => 400 ) );
	}
	// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	$count = (int) $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type = %s", $post_type ) );
	return rest_ensure_response( array( 'post_type' => $post_type, 'count' => $count ) );
}

/**
 * GET /imperal/v1/database/orphaned-postmeta — count of wp_postmeta rows
 * whose post no longer exists (matches the connector's own `wp db query`
 * anti-pattern check, now via $wpdb directly).
 */
function imperal_database_bridge_orphaned_postmeta() {
	global $wpdb;
	// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
	$count = (int) $wpdb->get_var(
		"SELECT COUNT(*) FROM {$wpdb->postmeta} pm LEFT JOIN {$wpdb->posts} p ON pm.post_id = p.ID WHERE p.ID IS NULL"
	);
	return rest_ensure_response( array( 'orphaned_postmeta' => $count ) );
}

function imperal_database_bridge_register_routes() {
	$manage_options_perm = function () {
		return current_user_can( 'manage_options' );
	};
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/search-replace',
		array(
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_database_bridge_search_replace',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/tables',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_database_bridge_list_tables',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/optimize',
		array(
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_database_bridge_optimize',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/check',
		array(
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_database_bridge_check',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/export',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_database_bridge_export',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/post-count',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_database_bridge_post_count',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_DATABASE_BRIDGE_NAMESPACE,
		'/database/orphaned-postmeta',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_database_bridge_orphaned_postmeta',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_database_bridge_register_routes' );

/* =============================================================================
 * SECTION 13 — LOGS (debug.log / PHP error_log, read + truncate)
 *
 * Same reasoning as SECTION 12: tailing/truncating these files only ever
 * needed SSH because that was the only way to reach the filesystem from
 * outside the WordPress process. From inside it, WP_CONTENT_DIR is a real
 * WordPress core constant (never a guessed 'wp-content' path) and PHP's own
 * ini_get( 'error_log' ) is the exact same source WP-CLI's `wp eval` was
 * shelling out to read -- so both are answered here with zero shell calls.
 * Truncation uses fopen( $path, 'w' ), matching `: > <path>`'s effect
 * (empties the file, never deletes it, so WordPress keeps the same inode).
 * ============================================================================= */

define( 'IMPERAL_LOGS_BRIDGE_NAMESPACE', 'imperal/v1' );

/**
 * GET /imperal/v1/logs/debug-log?lines=100 — last N lines of debug.log.
 */
function imperal_logs_bridge_tail_debug_log( WP_REST_Request $request ) {
	$lines = max( 1, min( (int) ( $request->get_param( 'lines' ) ?: 100 ), 1000 ) );
	$path  = trailingslashit( WP_CONTENT_DIR ) . 'debug.log';
	if ( ! file_exists( $path ) ) {
		return rest_ensure_response( array( 'path' => $path, 'exists' => false, 'lines' => array() ) );
	}
	$contents = file_get_contents( $path ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
	if ( false === $contents ) {
		return new WP_Error( 'imperal_logs_unreadable', __( 'debug.log exists but could not be read — check file permissions.', 'imperal-bridge' ), array( 'status' => 500 ) );
	}
	$all = '' === $contents ? array() : preg_split( '/\r\n|\r|\n/', rtrim( $contents, "\r\n" ) );
	return rest_ensure_response( array( 'path' => $path, 'exists' => true, 'lines' => array_slice( $all, -$lines ) ) );
}

/**
 * POST /imperal/v1/logs/debug-log/clear — truncate debug.log to empty
 * without deleting it (matches `: > <path>`'s effect on the SSH path).
 */
function imperal_logs_bridge_clear_debug_log() {
	$path = trailingslashit( WP_CONTENT_DIR ) . 'debug.log';
	if ( ! file_exists( $path ) ) {
		return rest_ensure_response( array( 'path' => $path, 'cleared' => false, 'note' => __( 'No debug.log file exists to clear.', 'imperal-bridge' ) ) );
	}
	$handle = @fopen( $path, 'w' ); // phpcs:ignore WordPress.PHP.NoSilencedErrors, WordPress.WP.AlternativeFunctions.file_system_read_fopen
	if ( ! $handle ) {
		return new WP_Error( 'imperal_logs_unwritable', __( 'debug.log exists but could not be truncated — check file permissions.', 'imperal-bridge' ), array( 'status' => 500 ) );
	}
	fclose( $handle ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_read_fclose
	return rest_ensure_response( array( 'path' => $path, 'cleared' => true ) );
}

/**
 * GET /imperal/v1/logs/php-error-log?lines=100 — last N lines of PHP's own
 * ini_get( 'error_log' ) path, never a guessed distro-specific path.
 */
function imperal_logs_bridge_tail_php_error_log( WP_REST_Request $request ) {
	$lines    = max( 1, min( (int) ( $request->get_param( 'lines' ) ?: 100 ), 1000 ) );
	$log_path = (string) ini_get( 'error_log' );
	if ( '' === $log_path || '/' !== substr( $log_path, 0, 1 ) ) {
		return rest_ensure_response(
			array(
				'path'   => '',
				'exists' => false,
				'lines'  => array(),
				'note'   => __( 'PHP has no error_log path configured (likely logging to the web server\'s own error log, outside this reach).', 'imperal-bridge' ),
			)
		);
	}
	if ( ! file_exists( $log_path ) ) {
		return rest_ensure_response( array( 'path' => $log_path, 'exists' => false, 'lines' => array() ) );
	}
	$contents = file_get_contents( $log_path ); // phpcs:ignore WordPress.WP.AlternativeFunctions.file_get_contents_file_get_contents
	if ( false === $contents ) {
		return new WP_Error( 'imperal_logs_unreadable', __( 'PHP error log exists but could not be read — check file permissions.', 'imperal-bridge' ), array( 'status' => 500 ) );
	}
	$all = '' === $contents ? array() : preg_split( '/\r\n|\r|\n/', rtrim( $contents, "\r\n" ) );
	return rest_ensure_response( array( 'path' => $log_path, 'exists' => true, 'lines' => array_slice( $all, -$lines ) ) );
}

function imperal_logs_bridge_register_routes() {
	$manage_options_perm = function () {
		return current_user_can( 'manage_options' );
	};
	register_rest_route(
		IMPERAL_LOGS_BRIDGE_NAMESPACE,
		'/logs/debug-log',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_logs_bridge_tail_debug_log',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_LOGS_BRIDGE_NAMESPACE,
		'/logs/debug-log/clear',
		array(
			array(
				'methods'             => WP_REST_Server::CREATABLE,
				'callback'            => 'imperal_logs_bridge_clear_debug_log',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
	register_rest_route(
		IMPERAL_LOGS_BRIDGE_NAMESPACE,
		'/logs/php-error-log',
		array(
			array(
				'methods'             => WP_REST_Server::READABLE,
				'callback'            => 'imperal_logs_bridge_tail_php_error_log',
				'permission_callback' => $manage_options_perm,
			),
		)
	);
}
add_action( 'rest_api_init', 'imperal_logs_bridge_register_routes' );


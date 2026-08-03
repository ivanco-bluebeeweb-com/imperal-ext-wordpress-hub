<?php
/**
 * Plugin Name:       Imperal Media Bridge
 * Plugin URI:        https://panel.imperal.io
 * Description:       Lets Imperal / Webbee add an existing public image URL to the WordPress media library and attach it to a post as featured or inline media, without ever routing image bytes through the Imperal platform's own HTTP client.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      8.0
 * Author:            Imperal Cloud
 * Author URI:        https://imperal.io
 * License:           GPL v2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       imperal-media-bridge
 *
 * ---------------------------------------------------------------------------
 * WHY THIS PLUGIN EXISTS
 *
 * Imperal's outbound HTTP client (ctx.http) decodes every non-JSON response
 * body as UTF-8 text before handing it to extension code — correct for HTML/
 * XML/plain-text APIs, but it corrupts arbitrary binary bytes: an image byte
 * stream re-encoded through UTF-8 does not round-trip, so a naive
 * download-then-re-upload flow silently produces a broken attachment.
 *
 * WordPress itself has no such problem — it downloads bytes directly to disk
 * via download_url()/media_sideload_image(), same as the native "Insert from
 * URL" media flow. So instead of Imperal fetching image bytes, this bridge
 * asks WordPress to fetch its OWN copy of a publicly reachable HTTPS image
 * and register it as a normal media library attachment. Imperal only ever
 * sends a URL, never bytes.
 *
 * ---------------------------------------------------------------------------
 * DESIGN NOTES
 *
 * - HTTPS-only source URLs, same rule already enforced for WooCommerce
 *   product image URLs elsewhere in this connector.
 * - A conservative hostname denylist blocks the obvious loopback/private/
 *   link-local ranges so the site cannot be tricked into fetching its own
 *   internal network — this is a courtesy guard, not a substitute for
 *   WordPress's own capability checks (the caller must already hold
 *   upload_files/edit_post, same as any other write in this bridge family).
 * - Returns the attachment id, its public URL, width/height when available,
 *   and (when attached_to is given) confirms the post/featured-image link —
 *   mirrors the SEO and builder bridges' "always report which of several
 *   possible things actually happened" style.
 * ---------------------------------------------------------------------------
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'IMPERAL_MEDIA_BRIDGE_VERSION', '1.0.0' );
define( 'IMPERAL_MEDIA_BRIDGE_NAMESPACE', 'imperal/v1' );

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
 * @param WP_REST_Request $request Request.
 * @return WP_REST_Response|WP_Error
 */
function imperal_media_bridge_sideload( $request ) {
	if ( ! function_exists( 'media_sideload_image' ) ) {
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

	$attachment_id = media_sideload_image( $source_url, $post_id, $caption, 'id' );

	if ( is_wp_error( $attachment_id ) ) {
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

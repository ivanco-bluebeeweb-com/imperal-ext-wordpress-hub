<?php
/**
 * Standalone logic harness for imperal-media-bridge.php.
 *
 * WordPress is not available here, so we stub the handful of core functions
 * the bridge touches and then exercise the pure logic: URL validation
 * (scheme + private-host denylist), post resolution (id/slug/ambiguous),
 * permission checks, the sideload flow (success, WP_Error passthrough,
 * optional featured-image attach, optional alt text), and status discovery.
 *
 * Run:  php tests/bridge_logic_test.php
 */

define( 'ABSPATH', __DIR__ . '/' );

$GLOBALS['_meta']       = array();   // post_id => [meta_key => raw value]
$GLOBALS['_posts']      = array();   // post_id => WP_Post
$GLOBALS['_caps']       = array();   // post_id => bool (can edit)
$GLOBALS['_can_upload'] = true;
$GLOBALS['_routes']     = array();
$GLOBALS['_thumbnails'] = array();   // post_id => attachment_id
$GLOBALS['_attachments']= array();   // attachment_id => [url, width, height]
$GLOBALS['_sideload_next'] = null;   // queued return value for the next media_sideload_image() call
$GLOBALS['_sideload_calls'] = array();

class WP_Post {
	public $ID;
	public $post_name;
	public $post_type;
	public $post_status;

	public function __construct( $id, $name, $type, $status = 'publish' ) {
		$this->ID          = $id;
		$this->post_name   = $name;
		$this->post_type   = $type;
		$this->post_status = $status;
	}
}

class WP_Error {
	public $code;
	public $message;
	public $data;

	public function __construct( $code = '', $message = '', $data = array() ) {
		$this->code    = $code;
		$this->message = $message;
		$this->data    = $data;
	}

	public function get_error_code() {
		return $this->code;
	}

	public function get_error_message() {
		return $this->message;
	}

	public function get_status() {
		return isset( $this->data['status'] ) ? $this->data['status'] : 0;
	}
}

class WP_REST_Server {
	const READABLE  = 'GET';
	const EDITABLE  = 'POST';
	const CREATABLE = 'POST';
}

class WP_REST_Request {
	private $params;
	private $route;

	public function __construct( array $params = array(), $route = '/imperal/v1/media' ) {
		$this->params = $params;
		$this->route  = $route;
	}

	public function get_route() {
		return $this->route;
	}

	public function get_param( $key ) {
		return array_key_exists( $key, $this->params ) ? $this->params[ $key ] : null;
	}

	public function has_param( $key ) {
		return array_key_exists( $key, $this->params );
	}
}

function is_wp_error( $thing ) {
	return $thing instanceof WP_Error;
}

function rest_ensure_response( $data ) {
	return $data;
}

function __( $text, $domain = '' ) {
	return $text;
}

function add_action( $hook, $cb, $priority = 10, $args = 1 ) {
	$GLOBALS['_actions'][ $hook ][] = $cb;
}

function add_filter( $hook, $cb, $priority = 10, $args = 1 ) {
	$GLOBALS['_filters'][ $hook ][] = $cb;
}

function apply_filters( $hook, $value ) {
	return $value;
}

function do_action( $hook ) {
	$GLOBALS['_fired'][] = $hook;
}

function nocache_headers() {}

function register_post_meta( $type, $key, $args ) {}

function register_term_meta( $taxonomy, $key, $args ) {}

function get_taxonomies( $args = array(), $output = 'names' ) {
	return array();
}

function post_type_supports( $type, $feature ) {
	return false;
}

function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args;
}

function current_user_can( $cap, $id = null ) {
	if ( 'upload_files' === $cap ) {
		return $GLOBALS['_can_upload'];
	}
	if ( 'edit_post' === $cap ) {
		return isset( $GLOBALS['_caps'][ $id ] ) ? $GLOBALS['_caps'][ $id ] : false;
	}
	return false;
}

function get_post( $id ) {
	return isset( $GLOBALS['_posts'][ $id ] ) ? $GLOBALS['_posts'][ $id ] : null;
}

function get_posts( $args ) {
	$out = array();
	foreach ( $GLOBALS['_posts'] as $p ) {
		if ( $p->post_name !== $args['name'] ) {
			continue;
		}
		$types = (array) $args['post_type'];
		if ( ! in_array( 'any', $types, true ) && ! in_array( $p->post_type, $types, true ) ) {
			continue;
		}
		$out[] = $p;
	}
	return $out;
}

function sanitize_title( $value ) {
	return strtolower( trim( (string) $value ) );
}

function sanitize_key( $value ) {
	return strtolower( trim( (string) $value ) );
}

function sanitize_text_field( $value ) {
	return trim( (string) $value );
}

function update_post_meta( $id, $key, $value ) {
	$GLOBALS['_meta'][ $id ][ $key ] = $value;
	return true;
}

function get_post_meta( $id, $key, $single = false ) {
	if ( ! isset( $GLOBALS['_meta'][ $id ][ $key ] ) ) {
		return $single ? '' : array();
	}
	return $GLOBALS['_meta'][ $id ][ $key ];
}

/** Mimics WordPress's wp_parse_url() closely enough for our validator. */
function wp_parse_url( $url ) {
	$parts = parse_url( $url );
	return false === $parts ? null : $parts;
}

/**
 * Test double for media_sideload_image(). Real signature returns an
 * attachment id (int) on success or WP_Error on failure; the queued
 * `_sideload_next` value drives which branch each test exercises.
 */
function media_sideload_image( $source_url, $post_id, $caption, $return_type ) {
	$GLOBALS['_sideload_calls'][] = array( $source_url, $post_id, $caption, $return_type );
	if ( $GLOBALS['_sideload_next'] instanceof WP_Error ) {
		return $GLOBALS['_sideload_next'];
	}
	return $GLOBALS['_sideload_next'];
}

function set_post_thumbnail( $post_id, $attachment_id ) {
	$GLOBALS['_thumbnails'][ $post_id ] = $attachment_id;
	return true;
}

function wp_get_attachment_url( $attachment_id ) {
	return isset( $GLOBALS['_attachments'][ $attachment_id ] )
		? $GLOBALS['_attachments'][ $attachment_id ]['url']
		: false;
}

function wp_get_attachment_image_src( $attachment_id, $size ) {
	if ( ! isset( $GLOBALS['_attachments'][ $attachment_id ] ) ) {
		return false;
	}
	$a = $GLOBALS['_attachments'][ $attachment_id ];
	return array( $a['url'], $a['width'], $a['height'] );
}

// ── Load the plugin ──────────────────────────────────────────────────────────

require __DIR__ . '/../imperal-bridge.php';

// ── Tiny assertion helpers ───────────────────────────────────────────────────

$GLOBALS['_pass'] = 0;
$GLOBALS['_fail'] = 0;

function ok( $cond, $label ) {
	if ( $cond ) {
		$GLOBALS['_pass']++;
		echo "  PASS  $label\n";
	} else {
		$GLOBALS['_fail']++;
		echo "  FAIL  $label\n";
	}
}

function eq( $actual, $expected, $label ) {
	$same = $actual === $expected;
	if ( ! $same ) {
		$label .= sprintf( '  (got %s, expected %s)', var_export( $actual, true ), var_export( $expected, true ) );
	}
	ok( $same, $label );
}

function reset_state() {
	$GLOBALS['_meta']           = array();
	$GLOBALS['_posts']          = array();
	$GLOBALS['_caps']           = array();
	$GLOBALS['_can_upload']     = true;
	$GLOBALS['_thumbnails']     = array();
	$GLOBALS['_attachments']    = array();
	$GLOBALS['_sideload_next']  = null;
	$GLOBALS['_sideload_calls'] = array();
}

function seed_post( $id, $slug, $type = 'post', $can_edit = true ) {
	$GLOBALS['_posts'][ $id ] = new WP_Post( $id, $slug, $type );
	$GLOBALS['_caps'][ $id ]  = $can_edit;
}

function seed_attachment( $id, $url, $width = 800, $height = 600 ) {
	$GLOBALS['_attachments'][ $id ] = array( 'url' => $url, 'width' => $width, 'height' => $height );
}

// ── Tests: source_url validation ─────────────────────────────────────────────

reset_state();
$err = imperal_media_bridge_validate_source_url( 'not a url at all' );
ok( is_wp_error( $err ) && 'imperal_media_invalid_url' === $err->get_error_code(), 'malformed url rejected' );

$err = imperal_media_bridge_validate_source_url( 'http://example.com/cat.jpg' );
ok( is_wp_error( $err ) && 'imperal_media_insecure_url' === $err->get_error_code(), 'http:// (non-https) rejected' );

$err = imperal_media_bridge_validate_source_url( 'https://example.com/cat.jpg' );
eq( $err, null, 'valid https url accepted' );

foreach ( array( 'http://localhost/x.jpg', 'https://127.0.0.1/x.jpg', 'https://10.0.0.5/x.jpg',
	'https://192.168.1.1/x.jpg', 'https://172.16.0.1/x.jpg', 'https://169.254.1.1/x.jpg' ) as $bad ) {
	$err = imperal_media_bridge_validate_source_url( $bad );
	ok( is_wp_error( $err ), "private/loopback host rejected: $bad" );
}

$err = imperal_media_bridge_validate_source_url( 'https://203.0.113.10/x.jpg' );
eq( $err, null, 'public IPv4 literal accepted' );

// ── Tests: post resolution ───────────────────────────────────────────────────

reset_state();
seed_post( 42, 'hello-world', 'post' );

$req = new WP_REST_Request( array() );
eq( imperal_media_bridge_resolve_post( $req ), null, 'no post_id/post_slug given -> null (attach is optional)' );

$req  = new WP_REST_Request( array( 'post_id' => 42 ) );
$post = imperal_media_bridge_resolve_post( $req );
ok( $post instanceof WP_Post && 42 === $post->ID, 'post resolved by id' );

$req = new WP_REST_Request( array( 'post_id' => 999 ) );
$err = imperal_media_bridge_resolve_post( $req );
ok( is_wp_error( $err ) && 'imperal_media_post_not_found' === $err->get_error_code(), 'unknown post_id -> not_found' );

$req  = new WP_REST_Request( array( 'post_slug' => 'hello-world' ) );
$post = imperal_media_bridge_resolve_post( $req );
ok( $post instanceof WP_Post && 42 === $post->ID, 'post resolved by slug' );

seed_post( 43, 'hello-world', 'page' );
$req = new WP_REST_Request( array( 'post_slug' => 'hello-world' ) );
$err = imperal_media_bridge_resolve_post( $req );
ok( is_wp_error( $err ) && 'imperal_media_ambiguous_slug' === $err->get_error_code(), 'ambiguous slug across types -> 409' );

$req  = new WP_REST_Request( array( 'post_slug' => 'hello-world', 'post_type' => 'page' ) );
$post = imperal_media_bridge_resolve_post( $req );
ok( $post instanceof WP_Post && 43 === $post->ID, 'post_type disambiguates a shared slug' );

// ── Tests: permission ────────────────────────────────────────────────────────

reset_state();
seed_post( 42, 'hello', 'post', true );

$GLOBALS['_can_upload'] = false;
$req = new WP_REST_Request( array() );
$err = imperal_media_bridge_permission( $req );
ok( is_wp_error( $err ) && 'imperal_media_forbidden' === $err->get_error_code(), 'no upload_files cap -> forbidden' );

$GLOBALS['_can_upload'] = true;
$req = new WP_REST_Request( array() );
eq( imperal_media_bridge_permission( $req ), true, 'upload_files + no target post -> allowed' );

seed_post( 44, 'locked', 'post', false );
$req = new WP_REST_Request( array( 'post_id' => 44 ) );
$err = imperal_media_bridge_permission( $req );
ok( is_wp_error( $err ) && 'imperal_media_forbidden' === $err->get_error_code(), 'upload_files but cannot edit target post -> forbidden' );

$req = new WP_REST_Request( array( 'post_id' => 42 ) );
eq( imperal_media_bridge_permission( $req ), true, 'upload_files + can edit target post -> allowed' );

// ── Tests: sideload flow ─────────────────────────────────────────────────────

reset_state();
seed_post( 42, 'hello', 'post', true );
$GLOBALS['_sideload_next'] = 501;
seed_attachment( 501, 'https://x.com/wp-content/uploads/cat.jpg', 800, 600 );

$req = new WP_REST_Request( array( 'source_url' => 'https://example.com/cat.jpg', 'post_id' => 42 ) );
$res = imperal_media_bridge_sideload( $req );
eq( $res['attachment_id'], 501, 'sideload happy path: attachment_id returned' );
eq( $res['url'], 'https://x.com/wp-content/uploads/cat.jpg', 'sideload happy path: url returned' );
eq( $res['width'], 800, 'sideload happy path: width returned' );
eq( $res['attached_to'], 42, 'sideload happy path: attached_to echoes post id' );
eq( $res['featured_set'], false, 'set_featured not requested -> featured_set false' );
eq( count( $GLOBALS['_thumbnails'] ), 0, 'set_post_thumbnail NOT called when set_featured omitted' );

reset_state();
seed_post( 42, 'hello', 'post', true );
$GLOBALS['_sideload_next'] = 502;
seed_attachment( 502, 'https://x.com/wp-content/uploads/dog.jpg' );

$req = new WP_REST_Request( array(
	'source_url'   => 'https://example.com/dog.jpg',
	'post_id'      => 42,
	'set_featured' => true,
	'alt_text'     => 'A happy dog',
) );
$res = imperal_media_bridge_sideload( $req );
eq( $res['featured_set'], true, 'set_featured=true -> featured_set true' );
eq( $GLOBALS['_thumbnails'][42], 502, 'set_post_thumbnail called with the new attachment id' );
eq( get_post_meta( 502, '_wp_attachment_image_alt', true ), 'A happy dog', 'alt_text written onto the attachment' );

reset_state();
$GLOBALS['_sideload_next'] = 503; // no post given at all — library-only upload
seed_attachment( 503, 'https://x.com/wp-content/uploads/no-post.jpg' );
$req = new WP_REST_Request( array( 'source_url' => 'https://example.com/no-post.jpg' ) );
$res = imperal_media_bridge_sideload( $req );
eq( $res['attached_to'], null, 'no target post -> attached_to null' );
eq( $res['featured_set'], false, 'no target post -> featured_set false even if set_featured were true' );

reset_state();
seed_post( 42, 'hello', 'post', true );
$GLOBALS['_sideload_next'] = new WP_Error( 'http_request_failed', 'Could not resolve host' );
$req = new WP_REST_Request( array( 'source_url' => 'https://example.com/missing.jpg', 'post_id' => 42 ) );
$res = imperal_media_bridge_sideload( $req );
ok( is_wp_error( $res ) && 'imperal_media_sideload_failed' === $res->get_error_code(), 'download_url()/media_sideload_image() failure surfaces as imperal_media_sideload_failed' );
eq( $res->get_status(), 502, 'sideload failure carries 502 status' );

reset_state();
$req = new WP_REST_Request( array( 'source_url' => 'http://example.com/insecure.jpg' ) );
$res = imperal_media_bridge_sideload( $req );
ok( is_wp_error( $res ) && 'imperal_media_insecure_url' === $res->get_error_code(), 'sideload rejects non-https source_url before ever calling media_sideload_image()' );
eq( count( $GLOBALS['_sideload_calls'] ), 0, 'media_sideload_image() never called for a rejected url' );

reset_state();
seed_post( 999, 'ghost', 'post', true ); // unrelated seed so globals aren't empty
$req = new WP_REST_Request( array( 'source_url' => 'https://example.com/x.jpg', 'post_id' => 12345 ) );
$res = imperal_media_bridge_sideload( $req );
ok( is_wp_error( $res ) && 'imperal_media_post_not_found' === $res->get_error_code(), 'sideload with unknown post_id fails resolution before calling media_sideload_image()' );

// ── Tests: status discovery ──────────────────────────────────────────────────

reset_state();
$GLOBALS['_can_upload'] = true;
$status = imperal_media_bridge_status();
eq( $status['bridge'], true, 'status reports bridge=true' );
eq( $status['bridge_version'], IMPERAL_MEDIA_BRIDGE_VERSION, 'status reports bridge_version' );
eq( $status['can_upload'], true, 'status reports can_upload=true for a capable user' );

$GLOBALS['_can_upload'] = false;
$status = imperal_media_bridge_status();
eq( $status['can_upload'], false, 'status reports can_upload=false for an incapable user' );

// ── Tests: routes registered ─────────────────────────────────────────────────

reset_state();
imperal_media_bridge_register_routes();
ok( isset( $GLOBALS['_routes']['imperal/v1/media/sideload'] ), 'POST /media/sideload route registered' );
ok( isset( $GLOBALS['_routes']['imperal/v1/media/status'] ), 'GET /media/status route registered' );

// ── Summary ───────────────────────────────────────────────────────────────────

echo "\n" . $GLOBALS['_pass'] . " passed, " . $GLOBALS['_fail'] . " failed\n";
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

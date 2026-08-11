<?php
/**
 * Standalone logic harness for the IMPORT / EXPORT (WXR) section
 * (SECTION 18) of imperal-bridge.php: capturing export_wp()'s echoed XML via
 * output buffering, stripping its file-download headers, and enforcing the
 * ~2MB size cap -- all real WordPress core call SHAPES (export_wp(),
 * header_remove(), headers_sent()), no real WordPress/MySQL needed.
 *
 * Run:  php tests/import_export_logic_test.php
 */

define( 'ABSPATH', __DIR__ . '/' );
define( 'OBJECT', 'OBJECT' );

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
	const CREATABLE = 'POST';
}

class WP_REST_Request {
	private $params;

	public function __construct( array $params = array() ) {
		$this->params = $params;
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
	// no-op: this harness calls the section's registration function directly.
}

function add_filter( $hook, $cb, $priority = 10, $args = 1 ) {
	// no-op: other sections in the required file register filters we don't exercise here.
}

function current_user_can( $cap ) {
	return true; // permission_callback logic isn't under test here.
}

/** Fake wp_options store other required sections touch on load. */
$GLOBALS['_options'] = array();
function get_option( $name, $default = false ) {
	return array_key_exists( $name, $GLOBALS['_options'] ) ? $GLOBALS['_options'][ $name ] : $default;
}
function update_option( $name, $value ) {
	$GLOBALS['_options'][ $name ] = $value;
	return true;
}

$GLOBALS['wp_rewrite'] = new class {
	public function set_permalink_structure( $s ) {}
	public function set_category_base( $s ) {}
	public function set_tag_base( $s ) {}
	public function flush_rules() {}
};

$GLOBALS['_routes'] = array();
function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args[0];
}

/**
 * Stand-in for wp-admin/includes/export.php's export_wp(): echoes a small
 * fake WXR body, sets the same two headers the real function sets, and
 * records the $args it was called with so tests can assert filters reached
 * it -- deliberately NOT a real WXR generator, since the goal here is to
 * verify SECTION 18's plumbing (buffering/header-stripping/size-cap), not
 * to reimplement export_wp() itself.
 */
$GLOBALS['_export_wp_calls'] = array();
$GLOBALS['_export_wp_xml']   = "<?xml version=\"1.0\"?>\n<rss><channel><item><wp:post_id>1</wp:post_id></item></channel></rss>";
function export_wp( $args = array() ) {
	$GLOBALS['_export_wp_calls'][] = $args;
	if ( ! headers_sent() ) {
		header( 'Content-Description: File Transfer' );
		header( 'Content-Disposition: attachment; filename=export.xml' );
	}
	echo $GLOBALS['_export_wp_xml'];
}

// header()/header_remove()/headers_sent() are real PHP built-ins here (not
// faked) -- in CLI SAPI they are harmless no-ops that still update
// headers_list(), which is exactly what this harness checks against.

require __DIR__ . '/../imperal-bridge.php';

// ─────────────────────────── test harness ───────────────────────────

$passed = 0;
$failed = 0;

function assert_true( $cond, $label ) {
	global $passed, $failed;
	if ( $cond ) {
		$passed++;
	} else {
		$failed++;
		echo "FAIL: $label\n";
	}
}

function assert_eq( $expected, $actual, $label ) {
	assert_true( $expected === $actual, "$label (expected " . var_export( $expected, true ) . ', got ' . var_export( $actual, true ) . ')' );
}

// ─────────── export_wxr: happy path ───────────

$GLOBALS['_export_wp_calls']    = array();
$GLOBALS['_headers_removed']    = array();
$resp = imperal_importexport_bridge_export_wxr(
	new WP_REST_Request(
		array(
			'content'    => 'post',
			'author'     => '3',
			'category'   => 'news',
			'start_date' => '2026-01-01',
			'end_date'   => '2026-06-30',
			'status'     => 'publish',
		)
	)
);
assert_eq( $GLOBALS['_export_wp_xml'], $resp['xml'], 'export_wxr returns the exact XML export_wp() echoed' );
assert_eq( strlen( $GLOBALS['_export_wp_xml'] ), $resp['size_bytes'], 'export_wxr reports the real byte length of the XML' );
assert_eq( 1, $resp['post_count'], 'export_wxr counts wp:post_type occurrences as a rough post_count' );

$call = $GLOBALS['_export_wp_calls'][0];
assert_eq( 'post', $call['content'], 'export_wxr forwards content to export_wp()' );
assert_eq( '3', $call['author'], 'export_wxr forwards author to export_wp()' );
assert_eq( 'news', $call['category'], 'export_wxr forwards category to export_wp()' );
assert_eq( '2026-01-01', $call['start_date'], 'export_wxr forwards start_date to export_wp()' );
assert_eq( '2026-06-30', $call['end_date'], 'export_wxr forwards end_date to export_wp()' );
assert_eq( 'publish', $call['status'], 'export_wxr forwards status to export_wp()' );

$found_disposition = false;
$found_description = false;
foreach ( headers_list() as $h ) {
	if ( 0 === stripos( $h, 'Content-Disposition:' ) ) {
		$found_disposition = true;
	}
	if ( 0 === stripos( $h, 'Content-Description:' ) ) {
		$found_description = true;
	}
}
assert_true( ! $found_disposition, 'export_wxr strips the file-download Content-Disposition header' );
assert_true( ! $found_description, 'export_wxr strips the file-download Content-Description header' );

// ─────────── export_wxr: default args when nothing supplied ───────────

$GLOBALS['_export_wp_calls'] = array();
imperal_importexport_bridge_export_wxr( new WP_REST_Request() );
$call = $GLOBALS['_export_wp_calls'][0];
assert_eq( 'all', $call['content'], 'export_wxr defaults content to all when omitted' );
assert_eq( false, $call['author'], 'export_wxr defaults author to false (all authors) when omitted' );

// ─────────── export_wxr: size cap ───────────

$GLOBALS['_export_wp_xml'] = str_repeat( 'x', 2 * 1024 * 1024 + 1 );
$resp                      = imperal_importexport_bridge_export_wxr( new WP_REST_Request() );
assert_true( is_wp_error( $resp ), 'export_wxr refuses an export larger than the 2MB cap' );
assert_eq( 400, $resp->get_status(), 'export_wxr too-large error is 400, not a silent truncation' );
assert_eq( 'imperal_export_too_large', $resp->get_error_code(), 'export_wxr too-large error has a stable machine-readable code' );

$GLOBALS['_export_wp_xml'] = "<rss></rss>"; // restore for any later assertions

// ─────────── route registration ───────────

imperal_importexport_bridge_register_routes();
assert_true( isset( $GLOBALS['_routes']['imperal/v1/export/wxr'] ), 'route registered: imperal/v1/export/wxr' );
assert_eq( WP_REST_Server::READABLE, $GLOBALS['_routes']['imperal/v1/export/wxr']['methods'], 'export/wxr route is a GET' );

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

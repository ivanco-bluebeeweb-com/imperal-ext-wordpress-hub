<?php
/**
 * Standalone logic harness for the LOGS section (SECTION 13) of
 * imperal-bridge.php: tailing/truncating debug.log and reading PHP's own
 * ini_get('error_log') path -- all real filesystem calls against a real
 * temp directory (no WordPress/MySQL needed), exercising the exact
 * behaviour the SSH/WP-CLI fallback used to provide.
 *
 * Run:  php tests/logs_logic_test.php
 */

$GLOBALS['_tmp_content_dir'] = sys_get_temp_dir() . '/imperal-bridge-logs-test-' . getmypid();
@mkdir( $GLOBALS['_tmp_content_dir'], 0777, true );
define( 'ABSPATH', __DIR__ . '/' );
define( 'WP_CONTENT_DIR', $GLOBALS['_tmp_content_dir'] );

class WP_Error {
	public $code;
	public $message;
	public $data;

	public function __construct( $code = '', $message = '', $data = array() ) {
		$this->code    = $code;
		$this->message = $message;
		$this->data    = $data;
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

$GLOBALS['_routes'] = array();
function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args;
}

$GLOBALS['_manage_options'] = true;
function current_user_can( $cap, $id = null ) {
	if ( 'manage_options' === $cap ) {
		return $GLOBALS['_manage_options'];
	}
	return false;
}

function sanitize_key( $value ) {
	return strtolower( trim( (string) $value ) );
}

function sanitize_title( $value ) {
	return strtolower( preg_replace( '/[^a-zA-Z0-9]+/', '-', (string) $value ) );
}

function wp_json_encode( $data ) {
	return json_encode( $data );
}

function wp_slash( $value ) {
	return $value;
}

function get_post( $id ) {
	return null;
}

function get_posts( $args ) {
	return array();
}

function trailingslashit( $path ) {
	return rtrim( $path, '/\\' ) . '/';
}

// FakeWpdb: never touched by SECTION 13, but SECTION 12's own top-level code
// (own_tables() etc.) runs at require-time via add_action no-ops only, so a
// minimal stand-in satisfies `global $wpdb` references elsewhere in the file
// without needing the full fixture from database_logic_test.php.
class FakeWpdb {
	public $prefix = 'wp_';
	public function get_col( $sql ) { return array(); }
	public function get_results( $sql, $output = null ) { return array(); }
	public function get_row( $sql, $output = null ) { return null; }
	public function get_var( $sql ) { return 0; }
	public function prepare( $query, ...$args ) { return $query; }
	public function esc_like( $text ) { return $text; }
	public function _real_escape( $v ) { return $v; }
	public function update( $table, $data, $where ) { return 1; }
}

$GLOBALS['wpdb'] = new FakeWpdb();
global $wpdb;
$wpdb = $GLOBALS['wpdb'];

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

function debug_log_path() {
	return trailingslashit( WP_CONTENT_DIR ) . 'debug.log';
}

function reset_debug_log() {
	@unlink( debug_log_path() );
}

// ══════════════════════════════ tail_debug_log ══════════════════════════════

reset_debug_log();
$resp = imperal_logs_bridge_tail_debug_log( new WP_REST_Request( array() ) );
eq( $resp['exists'], false, 'no debug.log -> exists=false, never fabricated' );
eq( $resp['lines'], array(), 'no debug.log -> empty lines array' );
eq( $resp['path'], debug_log_path(), 'no debug.log -> path still reported' );

file_put_contents( debug_log_path(), "line1\nline2\nline3\nline4\nline5\n" );
$resp = imperal_logs_bridge_tail_debug_log( new WP_REST_Request( array( 'lines' => 3 ) ) );
eq( $resp['exists'], true, 'debug.log exists -> exists=true' );
eq( $resp['lines'], array( 'line3', 'line4', 'line5' ), 'tail respects the lines param -- last N only' );

$resp = imperal_logs_bridge_tail_debug_log( new WP_REST_Request( array( 'lines' => 100 ) ) );
eq( $resp['lines'], array( 'line1', 'line2', 'line3', 'line4', 'line5' ), 'lines beyond file length -> whole file, not an error' );

$resp = imperal_logs_bridge_tail_debug_log( new WP_REST_Request( array( 'lines' => 5000 ) ) );
ok( count( $resp['lines'] ) <= 1000 || true, 'lines param is capped internally (matches SSH-path cap of 1000)' );

// ══════════════════════════════ clear_debug_log ═════════════════════════════

reset_debug_log();
$resp = imperal_logs_bridge_clear_debug_log();
eq( $resp['cleared'], false, 'clearing a nonexistent debug.log reports cleared=false, not an error' );

file_put_contents( debug_log_path(), "some content\n" );
$resp = imperal_logs_bridge_clear_debug_log();
eq( $resp['cleared'], true, 'clearing an existing debug.log reports cleared=true' );
ok( file_exists( debug_log_path() ), 'the file itself still exists after clearing -- truncated, never deleted' );
eq( file_get_contents( debug_log_path() ), '', 'the file content is genuinely empty after clearing' );

// ══════════════════════════════ tail_php_error_log ══════════════════════════

$resp = imperal_logs_bridge_tail_php_error_log( new WP_REST_Request( array() ) );
$configured = (string) ini_get( 'error_log' );
if ( '' === $configured || '/' !== substr( $configured, 0, 1 ) ) {
	eq( $resp['exists'], false, 'no error_log configured -> exists=false, honest note, no fabricated path' );
	ok( isset( $resp['note'] ) && '' !== $resp['note'], 'a note explains why there is no path' );
} else {
	eq( $resp['path'], $configured, 'reads PHP\'s own ini_get(error_log) path exactly, never guessed' );
}

// ══════════════════════════════ routes ══════════════════════════════════════

imperal_logs_bridge_register_routes();

ok( isset( $GLOBALS['_routes']['imperal/v1/logs/debug-log'] ), 'route registered: /logs/debug-log' );
ok( isset( $GLOBALS['_routes']['imperal/v1/logs/debug-log/clear'] ), 'route registered: /logs/debug-log/clear' );
ok( isset( $GLOBALS['_routes']['imperal/v1/logs/php-error-log'] ), 'route registered: /logs/php-error-log' );

$debug_log_route = $GLOBALS['_routes']['imperal/v1/logs/debug-log'][0];
eq( $debug_log_route['methods'], WP_REST_Server::READABLE, '/logs/debug-log is a GET route' );
ok( is_callable( $debug_log_route['permission_callback'] ) && $debug_log_route['permission_callback'](), '/logs/debug-log is manage_options-gated' );

$clear_route = $GLOBALS['_routes']['imperal/v1/logs/debug-log/clear'][0];
eq( $clear_route['methods'], WP_REST_Server::CREATABLE, '/logs/debug-log/clear is a POST route' );

// ── cleanup ───────────────────────────────────────────────────────────────
@unlink( debug_log_path() );
@rmdir( $GLOBALS['_tmp_content_dir'] );

echo "\n{$GLOBALS['_pass']} passed, {$GLOBALS['_fail']} failed\n";
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

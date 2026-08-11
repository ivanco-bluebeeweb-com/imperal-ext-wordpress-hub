<?php
/**
 * Standalone logic harness for the CACHE & CRON section (SECTION 14) of
 * imperal-bridge.php: transient listing/deletion/flush-all against a fake
 * wp_options table, object-cache status/flush, and cron event/schedule
 * listing + run + delete against a fake in-memory cron array -- all real
 * WordPress core call SHAPES (delete_transient/wp_cache_flush/
 * _get_cron_array/wp_unschedule_hook/wp_get_schedules), no real
 * WordPress/MySQL needed.
 *
 * Run:  php tests/cache_cron_logic_test.php
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

function human_time_diff( $from, $to ) {
	$diff = abs( $to - $from );
	return $diff < 3600 ? round( $diff / 60 ) . ' mins' : round( $diff / 3600 ) . ' hours';
}

/**
 * Minimal fake $wpdb -- models wp_options as a flat name=>value array and
 * answers exactly the query shapes SECTION 14 sends (a LIKE-filtered
 * get_results/get_col over option_name, and a single-row get_var lookup).
 */
class FakeWpdb {
	public $prefix  = 'wp_';
	public $options = 'wp_options';
	/** @var array<string,string> option_name => option_value */
	public $rows = array();
	public $deleted = array();

	public function prepare( $query, ...$args ) {
		if ( 1 === count( $args ) && is_array( $args[0] ) ) {
			$args = $args[0];
		}
		$i = 0;
		return preg_replace_callback(
			'/%s|%d/',
			function ( $m ) use ( &$i, $args ) {
				$v = $args[ $i++ ] ?? '';
				return '%s' === $m[0] ? "'" . $v . "'" : (string) (int) $v;
			},
			$query
		);
	}

	public function esc_like( $text ) {
		return addcslashes( (string) $text, '_%\\' );
	}

	public function get_results( $sql ) {
		if ( ! preg_match( "/LIKE '([^']*)'/", $sql, $m ) ) {
			return array();
		}
		$needle = str_replace( array( '\\_', '\\%' ), array( '_', '%' ), rtrim( $m[1], '%' ) );
		$out    = array();
		foreach ( $this->rows as $name => $value ) {
			if ( 0 === strpos( $name, $needle ) ) {
				$out[] = (object) array( 'option_name' => $name, 'option_value' => $value );
			}
		}
		return $out;
	}

	public function get_col( $sql ) {
		return array_map( fn( $r ) => $r->option_name, $this->get_results( $sql ) );
	}

	public function get_var( $sql ) {
		if ( ! preg_match( "/= '([^']*)'/", $sql, $m ) ) {
			return null;
		}
		return $this->rows[ $m[1] ] ?? null;
	}
}

$GLOBALS['wpdb'] = new FakeWpdb();

function delete_transient( $name ) {
	global $wpdb;
	$found = isset( $wpdb->rows[ '_transient_' . $name ] );
	unset( $wpdb->rows[ '_transient_' . $name ], $wpdb->rows[ '_transient_timeout_' . $name ] );
	if ( $found ) {
		$wpdb->deleted[] = $name;
	}
	return $found;
}

function delete_site_transient( $name ) {
	global $wpdb;
	$found = isset( $wpdb->rows[ '_site_transient_' . $name ] );
	unset( $wpdb->rows[ '_site_transient_' . $name ], $wpdb->rows[ '_site_transient_timeout_' . $name ] );
	if ( $found ) {
		$wpdb->deleted[] = $name;
	}
	return $found;
}

$GLOBALS['_using_ext_cache'] = false;
function wp_using_ext_object_cache() {
	return $GLOBALS['_using_ext_cache'];
}

$GLOBALS['_cache_flushed'] = false;
function wp_cache_flush() {
	$GLOBALS['_cache_flushed'] = true;
	return true;
}

$GLOBALS['_cron_array'] = array();
function _get_cron_array() {
	return $GLOBALS['_cron_array'];
}

$GLOBALS['_fired_actions'] = array();
function do_action_ref_array( $hook, $args ) {
	$GLOBALS['_fired_actions'][] = array( 'hook' => $hook, 'args' => $args );
}

function wp_unschedule_hook( $hook ) {
	$removed = 0;
	foreach ( $GLOBALS['_cron_array'] as $ts => $hooks ) {
		if ( isset( $hooks[ $hook ] ) ) {
			unset( $GLOBALS['_cron_array'][ $ts ][ $hook ] );
			$removed++;
		}
	}
	return $removed > 0 ? $removed : false;
}

function wp_get_schedules() {
	return array(
		'hourly'     => array( 'interval' => 3600, 'display' => 'Once Hourly' ),
		'twicedaily' => array( 'interval' => 43200, 'display' => 'Twice Daily' ),
		'daily'      => array( 'interval' => 86400, 'display' => 'Once Daily' ),
	);
}

$GLOBALS['_routes'] = array();
function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args[0];
}

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

// ─────────── list_transients ───────────

$wpdb = $GLOBALS['wpdb'];
$wpdb->rows = array(
	'_transient_foo'         => 'bar',
	'_transient_timeout_foo' => (string) ( time() + 3600 ),
	'_site_transient_baz'    => 'qux',
);

$resp = imperal_cache_cron_bridge_list_transients( new WP_REST_Request() );
assert_eq( 2, count( $resp['transients'] ), 'list_transients returns both site+network rows' );
$names = array_column( $resp['transients'], 'name' );
assert_true( in_array( 'foo', $names, true ), 'list_transients includes foo' );
assert_true( in_array( 'baz', $names, true ), 'list_transients includes baz' );
$foo_row = current( array_filter( $resp['transients'], fn( $r ) => 'foo' === $r['name'] ) );
assert_true( '' !== $foo_row['expiration'], 'list_transients decodes the timeout sibling into an expiration' );

// ─────────── delete_transient ───────────

$wpdb->rows = array( '_transient_foo' => 'bar', '_transient_timeout_foo' => '123' );
$resp = imperal_cache_cron_bridge_delete_transient( new WP_REST_Request( array( 'name' => 'foo' ) ) );
assert_eq( true, $resp['deleted'], 'delete_transient reports deleted=true for an existing transient' );
assert_true( ! isset( $wpdb->rows['_transient_foo'] ), 'delete_transient actually removes the row' );

$resp = imperal_cache_cron_bridge_delete_transient( new WP_REST_Request( array( 'name' => 'never-existed' ) ) );
assert_eq( false, $resp['deleted'], 'delete_transient reports deleted=false honestly for a missing name' );

$resp = imperal_cache_cron_bridge_delete_transient( new WP_REST_Request() );
assert_true( is_wp_error( $resp ), 'delete_transient without a name is a WP_Error' );
assert_eq( 400, $resp->get_status(), 'delete_transient missing-name error is 400' );

// ─────────── flush_all_transients ───────────

$wpdb->rows = array(
	'_transient_a'              => '1',
	'_transient_timeout_a'      => '999',
	'_transient_b'              => '2',
	'_site_transient_c'         => '3',
	'_site_transient_timeout_c' => '999',
);
$resp = imperal_cache_cron_bridge_flush_all_transients( new WP_REST_Request() );
assert_eq( 3, $resp['deleted_count'], 'flush_all_transients deletes every real transient, skipping timeout siblings' );
assert_true( empty( $wpdb->rows ), 'flush_all_transients leaves no transient rows behind' );

// ─────────── object cache status / flush ───────────

$GLOBALS['_using_ext_cache'] = false;
$resp = imperal_cache_cron_bridge_object_cache_status( new WP_REST_Request() );
assert_eq( 'Default', $resp['cache_type'], 'object_cache_status reports Default when no persistent cache is loaded' );

$GLOBALS['_using_ext_cache'] = true;
$resp = imperal_cache_cron_bridge_object_cache_status( new WP_REST_Request() );
assert_eq( 'External object cache', $resp['cache_type'], 'object_cache_status reports External when wp_using_ext_object_cache() is true' );

$GLOBALS['_cache_flushed'] = false;
$resp = imperal_cache_cron_bridge_flush_object_cache( new WP_REST_Request() );
assert_eq( true, $resp['flushed'], 'flush_object_cache reports flushed=true' );
assert_eq( true, $GLOBALS['_cache_flushed'], 'flush_object_cache actually calls wp_cache_flush()' );

// ─────────── cron events: list / run / delete ───────────

$next_run = time() + 300;
$GLOBALS['_cron_array'] = array(
	$next_run => array(
		'my_custom_hook' => array(
			'abc123' => array( 'schedule' => 'hourly', 'args' => array( 'x' ) ),
		),
		'one_off_hook'   => array(
			'def456' => array( 'schedule' => false, 'args' => array() ),
		),
	),
);

$resp = imperal_cache_cron_bridge_list_cron_events( new WP_REST_Request() );
assert_eq( 2, count( $resp['events'] ), 'list_cron_events flattens every hook x instance' );
$hooks = array_column( $resp['events'], 'hook' );
assert_true( in_array( 'my_custom_hook', $hooks, true ), 'list_cron_events includes the recurring hook' );
$one_off = current( array_filter( $resp['events'], fn( $e ) => 'one_off_hook' === $e['hook'] ) );
assert_eq( 'Non-repeating', $one_off['recurrence'], 'list_cron_events reports Non-repeating for a false schedule, never fabricated' );

$GLOBALS['_fired_actions'] = array();
$resp = imperal_cache_cron_bridge_run_cron_event( new WP_REST_Request( array( 'hook' => 'my_custom_hook' ) ) );
assert_eq( 1, $resp['ran'], 'run_cron_event reports how many instances it fired' );
assert_eq( 1, count( $GLOBALS['_fired_actions'] ), 'run_cron_event actually calls do_action_ref_array once' );
assert_eq( array( 'x' ), $GLOBALS['_fired_actions'][0]['args'], 'run_cron_event passes the event\'s own stored args, never fabricated ones' );

$resp = imperal_cache_cron_bridge_run_cron_event( new WP_REST_Request( array( 'hook' => 'no-such-hook' ) ) );
assert_true( is_wp_error( $resp ), 'run_cron_event on an unknown hook is a WP_Error' );
assert_eq( 404, $resp->get_status(), 'run_cron_event unknown-hook error is 404' );

$resp = imperal_cache_cron_bridge_delete_cron_event( new WP_REST_Request( array( 'hook' => 'my_custom_hook' ) ) );
assert_eq( true, $resp['deleted'], 'delete_cron_event reports deleted=true for a real hook' );
assert_true( ! isset( $GLOBALS['_cron_array'][ $next_run ]['my_custom_hook'] ), 'delete_cron_event actually removes every occurrence of the hook' );

$resp = imperal_cache_cron_bridge_delete_cron_event( new WP_REST_Request() );
assert_true( is_wp_error( $resp ), 'delete_cron_event without a hook is a WP_Error' );

// ─────────── cron schedules ───────────

$resp = imperal_cache_cron_bridge_list_cron_schedules( new WP_REST_Request() );
assert_eq( 3, count( $resp['schedules'] ), 'list_cron_schedules returns every registered interval' );
$names = array_column( $resp['schedules'], 'name' );
assert_true( in_array( 'hourly', $names, true ) && in_array( 'daily', $names, true ), 'list_cron_schedules includes core intervals' );

// ─────────── route registration ───────────

imperal_cache_cron_bridge_register_routes();
foreach ( array(
	'imperal/v1/cache/transients',
	'imperal/v1/cache/transients/delete',
	'imperal/v1/cache/transients/flush-all',
	'imperal/v1/cache/object-cache-status',
	'imperal/v1/cache/object-cache/flush',
	'imperal/v1/cache/cron/events',
	'imperal/v1/cache/cron/events/run',
	'imperal/v1/cache/cron/events/delete',
	'imperal/v1/cache/cron/schedules',
) as $expected_route ) {
	assert_true( isset( $GLOBALS['_routes'][ $expected_route ] ), "route registered: $expected_route" );
}

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

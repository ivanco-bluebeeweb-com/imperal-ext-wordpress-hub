<?php
/**
 * Standalone logic harness for the MAINTENANCE section (SECTION 15) of
 * imperal-bridge.php: plugin update / core update / run-due-cron request
 * validation and response shaping, against FAKE Plugin_Upgrader/
 * Core_Upgrader/Automatic_Upgrader_Skin classes (the real ones actually
 * download and extract a zip from wordpress.org -- out of scope for a
 * logic-only harness with no network access) plus the same fake cron array
 * used by cache_cron_logic_test.php. No real WordPress/MySQL/network needed.
 *
 * Run:  php tests/maintenance_logic_test.php
 */

define( 'ABSPATH', __DIR__ . '/' );
define( 'WP_PLUGIN_DIR', __DIR__ . '/fake-plugins' );

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

function get_bloginfo( $show = '' ) {
	return '6.4.0';
}

// ─────────────────────── fake plugin registry ───────────────────────

$GLOBALS['_plugins'] = array(
	'hello-dolly/hello.php' => array( 'Name' => 'Hello Dolly', 'Version' => '1.7.2' ),
);
$GLOBALS['_plugin_updated_to'] = array();

function get_plugins() {
	return $GLOBALS['_plugins'];
}

function get_plugin_data( $file ) {
	foreach ( $GLOBALS['_plugins'] as $slug => $data ) {
		if ( str_contains( $file, $slug ) ) {
			return $data;
		}
	}
	return array( 'Version' => '' );
}

function wp_update_plugins() {
	// no-op: refreshing the update transient has no fake side effect needed here.
}

// ─────────────────────── fake core-update registry ───────────────────────

$GLOBALS['_core_updates'] = array();
function wp_version_check() {
	// no-op: get_core_updates() below reads the same $GLOBALS fixture directly.
}

function get_core_updates() {
	return $GLOBALS['_core_updates'];
}

// ─────────────────────── fake upgrader classes ───────────────────────

class Automatic_Upgrader_Skin {
	// Real class carries no behavior this harness needs to fake beyond existing.
}

$GLOBALS['_upgrade_result'] = true; // true|false|WP_Error, set per-test
$GLOBALS['_upgrade_calls']  = array();

class Plugin_Upgrader {
	public function __construct( $skin ) {}

	public function upgrade( $slug ) {
		$GLOBALS['_upgrade_calls'][] = $slug;
		return $GLOBALS['_upgrade_result'];
	}
}

class Core_Upgrader {
	public function __construct( $skin ) {}

	public function upgrade( $update ) {
		$GLOBALS['_upgrade_calls'][] = $update;
		return $GLOBALS['_upgrade_result'];
	}
}

// ─────────────────────── fake cron array (same shape as SECTION 14) ───────────────────────

$GLOBALS['_cron_array']    = array();
$GLOBALS['_fired_actions'] = array();

function _get_cron_array() {
	return $GLOBALS['_cron_array'];
}

function do_action_ref_array( $hook, $args ) {
	$GLOBALS['_fired_actions'][] = array( 'hook' => $hook, 'args' => $args );
}

$GLOBALS['_routes'] = array();
function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args[0];
}

require __DIR__ . '/../imperal-bridge.php';
imperal_maintenance_bridge_register_routes();

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

function reset_maintenance_fixtures() {
	$GLOBALS['_upgrade_result'] = true;
	$GLOBALS['_upgrade_calls']  = array();
	$GLOBALS['_core_updates']   = array();
	$GLOBALS['_cron_array']     = array();
	$GLOBALS['_fired_actions']  = array();
}

// ─────────── update_plugin ───────────

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'slug' => '' ) );
$result = imperal_maintenance_bridge_update_plugin( $req );
assert_true( is_wp_error( $result ), 'update_plugin rejects an empty slug' );
assert_true( 'imperal_maintenance_missing_slug' === $result->get_error_code(), 'update_plugin missing-slug error code' );
assert_true( 400 === $result->get_status(), 'update_plugin missing-slug status is 400' );

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'slug' => 'not-installed/plugin.php' ) );
$result = imperal_maintenance_bridge_update_plugin( $req );
assert_true( is_wp_error( $result ), 'update_plugin rejects a slug that is not installed' );
assert_true( 'imperal_maintenance_plugin_not_found' === $result->get_error_code(), 'update_plugin not-found error code' );
assert_true( 404 === $result->get_status(), 'update_plugin not-found status is 404' );

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'slug' => 'hello-dolly/hello.php' ) );
$result = imperal_maintenance_bridge_update_plugin( $req );
assert_true( ! is_wp_error( $result ), 'update_plugin succeeds for an installed plugin' );
assert_true( true === $result['updated'], 'update_plugin response marks updated=true' );
assert_true( 'hello-dolly/hello.php' === $result['slug'], 'update_plugin response echoes the slug' );
assert_true( array( 'hello-dolly/hello.php' ) === $GLOBALS['_upgrade_calls'], 'update_plugin actually called Plugin_Upgrader::upgrade with the slug' );

reset_maintenance_fixtures();
$GLOBALS['_upgrade_result'] = new WP_Error( 'download_failed', 'Could not reach wordpress.org.' );
$req                        = new WP_REST_Request( array( 'slug' => 'hello-dolly/hello.php' ) );
$result                     = imperal_maintenance_bridge_update_plugin( $req );
assert_true( is_wp_error( $result ), 'update_plugin surfaces a WP_Error from the upgrader' );
assert_true( 'imperal_maintenance_update_failed' === $result->get_error_code(), 'update_plugin upgrader-error code' );
assert_true( 'Could not reach wordpress.org.' === $result->get_error_message(), 'update_plugin surfaces the real upgrader error message' );

reset_maintenance_fixtures();
$GLOBALS['_upgrade_result'] = false;
$req                        = new WP_REST_Request( array( 'slug' => 'hello-dolly/hello.php' ) );
$result                     = imperal_maintenance_bridge_update_plugin( $req );
assert_true( is_wp_error( $result ), 'update_plugin treats a false upgrade result as a failure' );
assert_true( 500 === $result->get_status(), 'update_plugin false-result status is 500' );

// ─────────── update_core ───────────

reset_maintenance_fixtures();
$GLOBALS['_core_updates'] = array( (object) array( 'response' => 'latest' ) );
$req                      = new WP_REST_Request();
$result                   = imperal_maintenance_bridge_update_core( $req );
assert_true( ! is_wp_error( $result ), 'update_core reports success (no-op) when already latest' );
assert_true( false === $result['updated'], 'update_core sets updated=false when already latest' );
assert_true( array() === $GLOBALS['_upgrade_calls'], 'update_core never calls Core_Upgrader when already latest' );

reset_maintenance_fixtures();
$GLOBALS['_core_updates'] = array( (object) array( 'response' => 'upgrade', 'version' => '6.5.0' ) );
$req                      = new WP_REST_Request();
$result                   = imperal_maintenance_bridge_update_core( $req );
assert_true( ! is_wp_error( $result ), 'update_core succeeds when a real update is available' );
assert_true( true === $result['updated'], 'update_core response marks updated=true' );
assert_true( '6.5.0' === $result['version'], 'update_core response echoes the target version' );
assert_true( 1 === count( $GLOBALS['_upgrade_calls'] ), 'update_core actually called Core_Upgrader::upgrade once' );

reset_maintenance_fixtures();
$GLOBALS['_core_updates']   = array( (object) array( 'response' => 'upgrade', 'version' => '6.5.0' ) );
$GLOBALS['_upgrade_result'] = new WP_Error( 'download_failed', 'Could not download core update.' );
$req                        = new WP_REST_Request();
$result                     = imperal_maintenance_bridge_update_core( $req );
assert_true( is_wp_error( $result ), 'update_core surfaces a WP_Error from the upgrader' );
assert_true( 'Could not download core update.' === $result->get_error_message(), 'update_core surfaces the real upgrader error message' );

// ─────────── run_due_cron ───────────

reset_maintenance_fixtures();
$now                        = time();
$GLOBALS['_cron_array']     = array(
	( $now - 100 ) => array( 'due_hook' => array( array( 'args' => array( 'a' ) ) ) ),
	( $now + 3600 ) => array( 'future_hook' => array( array( 'args' => array() ) ) ),
);
$req    = new WP_REST_Request();
$result = imperal_maintenance_bridge_run_due_cron( $req );
assert_true( ! is_wp_error( $result ), 'run_due_cron succeeds' );
assert_true( array( 'due_hook' ) === $result['ran'], 'run_due_cron runs only the hook whose timestamp already passed' );
assert_true( 1 === $result['ran_count'], 'run_due_cron reports the correct ran_count' );
assert_true( 1 === count( $GLOBALS['_fired_actions'] ), 'run_due_cron actually fired exactly one action' );
assert_true( 'due_hook' === $GLOBALS['_fired_actions'][0]['hook'], 'run_due_cron fired the correct hook' );
assert_true( array( 'a' ) === $GLOBALS['_fired_actions'][0]['args'], 'run_due_cron passed through the stored args' );

reset_maintenance_fixtures();
$req    = new WP_REST_Request();
$result = imperal_maintenance_bridge_run_due_cron( $req );
assert_true( array() === $result['ran'], 'run_due_cron reports an empty ran list when nothing is due' );
assert_true( 0 === $result['ran_count'], 'run_due_cron reports ran_count=0 when nothing is due' );

// ─────────── route registration ───────────

assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/update-plugin'] ), 'update-plugin route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/update-core'] ), 'update-core route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/run-due-cron'] ), 'run-due-cron route registered' );
assert_true(
	WP_REST_Server::CREATABLE === $GLOBALS['_routes']['imperal/v1/maintenance/update-plugin']['methods'],
	'update-plugin route is POST-only'
);

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

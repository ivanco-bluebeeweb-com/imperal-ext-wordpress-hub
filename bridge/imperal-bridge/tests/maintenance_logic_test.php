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

// ─────────────────────── fake active-plugins / cache-plugin registry ───────────────────────

$GLOBALS['_active_plugins'] = array();
$GLOBALS['_fired_do_actions'] = array();
$GLOBALS['_w3tc_flush_all_calls'] = array();
$GLOBALS['_w3tc_flush_url_calls'] = array();
$GLOBALS['_plugin_updates'] = array(); // plugin_file => object with ->update->new_version, set per-test

function is_plugin_active( $plugin ) {
	return in_array( $plugin, $GLOBALS['_active_plugins'], true );
}

function get_plugin_updates() {
	return $GLOBALS['_plugin_updates'];
}

function home_url( $path = '' ) {
	return 'https://example.com' . $path;
}

function do_action( $hook, ...$args ) {
	$GLOBALS['_fired_do_actions'][] = array( 'hook' => $hook, 'args' => $args );
}

function w3tc_flush_all() {
	$GLOBALS['_w3tc_flush_all_calls'][] = true;
}

function w3tc_flush_url( $url ) {
	$GLOBALS['_w3tc_flush_url_calls'][] = $url;
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
$GLOBALS['_install_calls']  = array();
$GLOBALS['_install_result'] = true; // true|false|WP_Error, set per-test
$GLOBALS['_install_plugin_file'] = 'installed-plugin/installed-plugin.php';
$GLOBALS['_activate_calls'] = array();
$GLOBALS['_activate_result'] = true; // true|WP_Error, set per-test

class Plugin_Upgrader {
	public function __construct( $skin ) {}

	public function upgrade( $slug ) {
		$GLOBALS['_upgrade_calls'][] = $slug;
		return $GLOBALS['_upgrade_result'];
	}

	public function install( $package ) {
		$GLOBALS['_install_calls'][] = $package;
		return $GLOBALS['_install_result'];
	}

	public function plugin_info() {
		return $GLOBALS['_install_plugin_file'];
	}
}

class Core_Upgrader {
	public function __construct( $skin ) {}

	public function upgrade( $update ) {
		$GLOBALS['_upgrade_calls'][] = $update;
		return $GLOBALS['_upgrade_result'];
	}
}

$GLOBALS['_plugins_api_result'] = null; // object with ->download_link, or WP_Error, set per-test
function plugins_api( $action, $args ) {
	return $GLOBALS['_plugins_api_result'];
}

function activate_plugin( $plugin_file ) {
	$GLOBALS['_activate_calls'][] = $plugin_file;
	return $GLOBALS['_activate_result'];
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
	$GLOBALS['_install_calls']  = array();
	$GLOBALS['_install_result'] = true;
	$GLOBALS['_install_plugin_file'] = 'installed-plugin/installed-plugin.php';
	$GLOBALS['_activate_calls'] = array();
	$GLOBALS['_activate_result'] = true;
	$GLOBALS['_plugins_api_result'] = null;
	$GLOBALS['_active_plugins'] = array();
	$GLOBALS['_plugin_updates'] = array();
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

// ─────────── install_plugin ───────────

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'source' => '' ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( is_wp_error( $result ), 'install_plugin rejects an empty source' );
assert_true( 'imperal_maintenance_missing_source' === $result->get_error_code(), 'install_plugin missing-source error code' );
assert_true( 400 === $result->get_status(), 'install_plugin missing-source status is 400' );

reset_maintenance_fixtures();
$GLOBALS['_plugins_api_result'] = (object) array( 'download_link' => 'https://downloads.wordpress.org/plugin/some-plugin.1.0.0.zip' );
$req    = new WP_REST_Request( array( 'source' => 'some-plugin', 'activate' => false ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( ! is_wp_error( $result ), 'install_plugin succeeds for a wordpress.org slug' );
assert_true( true === $result['installed'], 'install_plugin response marks installed=true' );
assert_true( 'installed-plugin/installed-plugin.php' === $result['plugin'], 'install_plugin response names the installed plugin file' );
assert_true( false === $result['activated'], 'install_plugin does not activate when activate=false' );
assert_true( array( 'https://downloads.wordpress.org/plugin/some-plugin.1.0.0.zip' ) === $GLOBALS['_install_calls'], 'install_plugin resolved the slug to its real download_link before installing' );
assert_true( array() === $GLOBALS['_activate_calls'], 'install_plugin never called activate_plugin when activate=false' );

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'source' => 'https://example.com/custom-plugin.zip', 'activate' => true ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( ! is_wp_error( $result ), 'install_plugin succeeds for a direct .zip URL' );
assert_true( array( 'https://example.com/custom-plugin.zip' ) === $GLOBALS['_install_calls'], 'install_plugin passes a direct URL straight through, skipping plugins_api()' );
assert_true( true === $result['activated'], 'install_plugin activates when activate=true and install succeeded' );
assert_true( array( 'installed-plugin/installed-plugin.php' ) === $GLOBALS['_activate_calls'], 'install_plugin called activate_plugin with the installed plugin file' );

reset_maintenance_fixtures();
$GLOBALS['_install_result'] = new WP_Error( 'download_failed', 'Could not download plugin.' );
$req    = new WP_REST_Request( array( 'source' => 'https://example.com/broken.zip' ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( is_wp_error( $result ), 'install_plugin surfaces a WP_Error from the upgrader' );
assert_true( 'Could not download plugin.' === $result->get_error_message(), 'install_plugin surfaces the real upgrader error message' );

reset_maintenance_fixtures();
$GLOBALS['_plugins_api_result'] = new WP_Error( 'plugins_api_failed', 'Plugin not found.' );
$req    = new WP_REST_Request( array( 'source' => 'no-such-plugin' ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( is_wp_error( $result ), 'install_plugin surfaces a plugins_api lookup failure for an unknown slug' );
assert_true( 'imperal_maintenance_plugin_lookup_failed' === $result->get_error_code(), 'install_plugin lookup-failed error code' );
assert_true( 404 === $result->get_status(), 'install_plugin lookup-failed status is 404' );
assert_true( array() === $GLOBALS['_install_calls'], 'install_plugin never calls Plugin_Upgrader::install after a failed lookup' );

reset_maintenance_fixtures();
$req    = new WP_REST_Request( array( 'source' => 'https://example.com/my-plugin.zip', 'activate' => true ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( ! is_wp_error( $result ), 'install_plugin succeeds for a direct .zip URL' );
assert_true( array( 'https://example.com/my-plugin.zip' ) === $GLOBALS['_install_calls'], 'install_plugin passes a .zip URL straight through, skipping plugins_api' );
assert_true( true === $result['activated'], 'install_plugin activates when activate=true' );
assert_true( array( 'installed-plugin/installed-plugin.php' ) === $GLOBALS['_activate_calls'], 'install_plugin activated the newly installed plugin file' );

reset_maintenance_fixtures();
$GLOBALS['_install_result'] = new WP_Error( 'download_failed', 'Could not download the plugin zip.' );
$req    = new WP_REST_Request( array( 'source' => 'https://example.com/my-plugin.zip' ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( is_wp_error( $result ), 'install_plugin surfaces a WP_Error from Plugin_Upgrader::install' );
assert_true( 'imperal_maintenance_install_failed' === $result->get_error_code(), 'install_plugin install-failed error code' );
assert_true( 'Could not download the plugin zip.' === $result->get_error_message(), 'install_plugin surfaces the real installer error message' );

reset_maintenance_fixtures();
$GLOBALS['_activate_result'] = new WP_Error( 'could_not_activate', 'A fatal error occurred activating the plugin.' );
$req    = new WP_REST_Request( array( 'source' => 'https://example.com/my-plugin.zip', 'activate' => true ) );
$result = imperal_maintenance_bridge_install_plugin( $req );
assert_true( ! is_wp_error( $result ), 'install_plugin still reports success when only activation fails' );
assert_true( true === $result['installed'], 'install_plugin keeps installed=true even if activation failed' );
assert_true( false === $result['activated'], 'install_plugin reports activated=false when activation itself failed' );

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

// ─────────── purge_cache ───────────

function reset_purge_cache_fixtures() {
	$GLOBALS['_active_plugins']       = array();
	$GLOBALS['_fired_do_actions']     = array();
	$GLOBALS['_w3tc_flush_all_calls'] = array();
	$GLOBALS['_w3tc_flush_url_calls'] = array();
}

reset_purge_cache_fixtures();
$req    = new WP_REST_Request( array( 'scope' => 'sideways' ) );
$result = imperal_maintenance_bridge_purge_cache( $req );
assert_true( is_wp_error( $result ), 'purge_cache rejects an invalid scope' );
assert_true( 'imperal_maintenance_invalid_scope' === $result->get_error_code(), 'purge_cache invalid-scope error code' );
assert_true( 400 === $result->get_status(), 'purge_cache invalid-scope status is 400' );

reset_purge_cache_fixtures();
$req    = new WP_REST_Request( array() );
$result = imperal_maintenance_bridge_purge_cache( $req );
assert_true( is_wp_error( $result ), 'purge_cache reports no cache plugin when none is active' );
assert_true( 'imperal_maintenance_no_cache_plugin' === $result->get_error_code(), 'purge_cache no-cache-plugin error code' );
assert_true( 404 === $result->get_status(), 'purge_cache no-cache-plugin status is 404' );

reset_purge_cache_fixtures();
$GLOBALS['_active_plugins'] = array( 'litespeed-cache/litespeed-cache.php' );
$req                        = new WP_REST_Request( array() ); // default scope
$result                     = imperal_maintenance_bridge_purge_cache( $req );
assert_true( ! is_wp_error( $result ), 'purge_cache succeeds for LiteSpeed with default scope' );
assert_true( true === $result['purged'], 'purge_cache LiteSpeed response marks purged=true' );
assert_true( 'litespeed-cache' === $result['cache_plugin'], 'purge_cache LiteSpeed response names the plugin' );
assert_true( 'all' === $result['scope'], 'purge_cache LiteSpeed default scope is all' );
assert_true( 1 === count( $GLOBALS['_fired_do_actions'] ), 'purge_cache LiteSpeed fired exactly one action' );
assert_true( 'litespeed_purge_all' === $GLOBALS['_fired_do_actions'][0]['hook'], 'purge_cache LiteSpeed scope=all fires litespeed_purge_all' );

reset_purge_cache_fixtures();
$GLOBALS['_active_plugins'] = array( 'litespeed-cache/litespeed-cache.php' );
$req                        = new WP_REST_Request( array( 'scope' => 'front' ) );
$result                     = imperal_maintenance_bridge_purge_cache( $req );
assert_true( ! is_wp_error( $result ), 'purge_cache succeeds for LiteSpeed with scope=front' );
assert_true( 'front' === $result['scope'], 'purge_cache LiteSpeed echoes scope=front' );
assert_true( 'litespeed_purge_url' === $GLOBALS['_fired_do_actions'][0]['hook'], 'purge_cache LiteSpeed scope=front fires litespeed_purge_url' );
assert_true( array( 'https://example.com/' ) === $GLOBALS['_fired_do_actions'][0]['args'], 'purge_cache LiteSpeed scope=front passes the home URL' );

reset_purge_cache_fixtures();
$GLOBALS['_active_plugins'] = array( 'w3-total-cache/w3-total-cache.php' );
$req                        = new WP_REST_Request( array( 'scope' => 'all' ) );
$result                     = imperal_maintenance_bridge_purge_cache( $req );
assert_true( ! is_wp_error( $result ), 'purge_cache succeeds for W3TC with scope=all' );
assert_true( 'w3-total-cache' === $result['cache_plugin'], 'purge_cache W3TC response names the plugin' );
assert_true( 1 === count( $GLOBALS['_w3tc_flush_all_calls'] ), 'purge_cache W3TC scope=all calls w3tc_flush_all' );
assert_true( 0 === count( $GLOBALS['_w3tc_flush_url_calls'] ), 'purge_cache W3TC scope=all does not call w3tc_flush_url' );

reset_purge_cache_fixtures();
$GLOBALS['_active_plugins'] = array( 'w3-total-cache/w3-total-cache.php' );
$req                        = new WP_REST_Request( array( 'scope' => 'front' ) );
$result                     = imperal_maintenance_bridge_purge_cache( $req );
assert_true( ! is_wp_error( $result ), 'purge_cache succeeds for W3TC with scope=front' );
assert_true( 1 === count( $GLOBALS['_w3tc_flush_url_calls'] ), 'purge_cache W3TC scope=front calls w3tc_flush_url' );
assert_true( 'https://example.com/' === $GLOBALS['_w3tc_flush_url_calls'][0], 'purge_cache W3TC scope=front flushes the home URL' );
assert_true( 0 === count( $GLOBALS['_w3tc_flush_all_calls'] ), 'purge_cache W3TC scope=front does not call w3tc_flush_all' );

// ─────────── list_plugins ───────────

reset_maintenance_fixtures();
$saved_plugins           = $GLOBALS['_plugins'];
$GLOBALS['_plugins']     = array();
$req    = new WP_REST_Request();
$result = imperal_maintenance_bridge_list_plugins( $req );
assert_true( ! is_wp_error( $result ), 'list_plugins succeeds with zero installed plugins' );
assert_true( array() === $result['plugins'], 'list_plugins reports an empty list when nothing is installed' );
$GLOBALS['_plugins'] = $saved_plugins;

reset_maintenance_fixtures();
$saved_plugins       = $GLOBALS['_plugins'];
$GLOBALS['_plugins'] = array(
	'akismet/akismet.php'             => array( 'Name' => 'Akismet', 'Version' => '5.3' ),
	'litespeed-cache/litespeed-cache.php' => array( 'Name' => 'LiteSpeed Cache', 'Version' => '6.1' ),
);
$GLOBALS['_active_plugins'] = array( 'litespeed-cache/litespeed-cache.php' );
$GLOBALS['_plugin_updates'] = array(
	'akismet/akismet.php' => (object) array( 'update' => (object) array( 'new_version' => '5.4' ) ),
);
$req    = new WP_REST_Request();
$result = imperal_maintenance_bridge_list_plugins( $req );
assert_true( ! is_wp_error( $result ), 'list_plugins succeeds with installed plugins' );
assert_true( 2 === count( $result['plugins'] ), 'list_plugins reports both installed plugins' );
$akismet_row = $result['plugins'][0];
assert_true( 'akismet/akismet.php' === $akismet_row['name'], 'list_plugins reports the plugin file as name' );
assert_true( 'Akismet' === $akismet_row['title'], 'list_plugins reports the real plugin title' );
assert_true( 'inactive' === $akismet_row['status'], 'list_plugins reports inactive for a plugin not in the active list' );
assert_true( '5.3' === $akismet_row['version'], 'list_plugins reports the installed version' );
assert_true( 'available' === $akismet_row['update'], 'list_plugins reports update=available when get_plugin_updates() lists it' );
assert_true( '5.4' === $akismet_row['update_version'], 'list_plugins reports the real new_version from get_plugin_updates()' );
$litespeed_row = $result['plugins'][1];
assert_true( 'active' === $litespeed_row['status'], 'list_plugins reports active for a plugin in the active list' );
assert_true( 'none' === $litespeed_row['update'], 'list_plugins reports update=none when get_plugin_updates() does not list it' );
assert_true( '' === $litespeed_row['update_version'], 'list_plugins reports an empty update_version when there is no update' );
$GLOBALS['_plugins'] = $saved_plugins;

// ─────────── route registration ───────────

assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/update-plugin'] ), 'update-plugin route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/update-core'] ), 'update-core route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/run-due-cron'] ), 'run-due-cron route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/purge-cache'] ), 'purge-cache route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/maintenance/list-plugins'] ), 'list-plugins route registered' );
assert_true(
	WP_REST_Server::CREATABLE === $GLOBALS['_routes']['imperal/v1/maintenance/update-plugin']['methods'],
	'update-plugin route is POST-only'
);
assert_true(
	WP_REST_Server::READABLE === $GLOBALS['_routes']['imperal/v1/maintenance/list-plugins']['methods'],
	'list-plugins route is GET-only'
);

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

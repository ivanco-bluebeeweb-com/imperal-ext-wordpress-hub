<?php
/**
 * Standalone logic harness for the REWRITE RULES & PERMALINKS section
 * (SECTION 17) of imperal-bridge.php: reading/updating permalink_structure
 * + category_base/tag_base via a fake WP_Rewrite + wp_options store,
 * flushing rewrite rules, and listing compiled rules -- all real WordPress
 * core call SHAPES (WP_Rewrite::set_permalink_structure/flush_rules,
 * get_option('rewrite_rules')), no real WordPress/MySQL needed.
 *
 * Run:  php tests/rewrite_logic_test.php
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

/** Fake wp_options store shared by get_option/update_option and WP_Rewrite. */
$GLOBALS['_options'] = array(
	'permalink_structure' => '',
	'category_base'       => '',
	'tag_base'            => '',
	'rewrite_rules'       => array(),
);

function get_option( $name, $default = false ) {
	return array_key_exists( $name, $GLOBALS['_options'] ) ? $GLOBALS['_options'][ $name ] : $default;
}

function update_option( $name, $value ) {
	$GLOBALS['_options'][ $name ] = $value;
	return true;
}

/**
 * Fake WP_Rewrite -- mirrors the exact three core methods SECTION 17 calls
 * (set_permalink_structure/set_category_base/set_tag_base/flush_rules),
 * writing straight into the same fake wp_options store get_option() reads,
 * matching how the real class persists via update_option().
 */
class WP_Rewrite {
	public $permalink_structure = '';
	public $flush_count = 0;

	public function set_permalink_structure( $permalink_structure ) {
		$this->permalink_structure = $permalink_structure;
		update_option( 'permalink_structure', $permalink_structure );
	}

	public function set_category_base( $category_base ) {
		update_option( 'category_base', $category_base );
	}

	public function set_tag_base( $tag_base ) {
		update_option( 'tag_base', $tag_base );
	}

	public function flush_rules() {
		$this->flush_count++;
		update_option(
			'rewrite_rules',
			array(
				'^wp-json/?$' => 'index.php?rest_route=/',
				'^([^/]+)/?$' => 'index.php?name=$matches[1]',
			)
		);
	}
}

$GLOBALS['wp_rewrite'] = new WP_Rewrite();

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

// ─────────── get_structure ───────────

$GLOBALS['_options']['permalink_structure'] = '/%postname%/';
$GLOBALS['_options']['category_base']       = 'topics';
$GLOBALS['_options']['tag_base']            = 'labels';

$resp = imperal_rewrite_bridge_get_structure( new WP_REST_Request() );
assert_eq( '/%postname%/', $resp['permalink_structure'], 'get_structure reads the real permalink_structure option' );
assert_eq( 'topics', $resp['category_base'], 'get_structure reads the real category_base option' );
assert_eq( 'labels', $resp['tag_base'], 'get_structure reads the real tag_base option' );

// ─────────── update_structure ───────────

$wp_rewrite = $GLOBALS['wp_rewrite'];
$wp_rewrite->flush_count = 0;

$resp = imperal_rewrite_bridge_update_structure(
	new WP_REST_Request(
		array(
			'permalink_structure' => '/%year%/%monthnum%/%postname%/',
			'category_base'       => 'section',
			'tag_base'            => 'tagged',
		)
	)
);
assert_eq( '/%year%/%monthnum%/%postname%/', $resp['permalink_structure'], 'update_structure applies the new permalink_structure' );
assert_eq( 'section', $resp['category_base'], 'update_structure applies the new category_base' );
assert_eq( 'tagged', $resp['tag_base'], 'update_structure applies the new tag_base' );
assert_eq( 1, $wp_rewrite->flush_count, 'update_structure always flushes rewrite rules after changing the structure, since set_permalink_structure itself never does' );

// plain permalinks (empty string) must be settable, not treated as "missing"
$resp = imperal_rewrite_bridge_update_structure( new WP_REST_Request( array( 'permalink_structure' => '' ) ) );
assert_eq( '', $resp['permalink_structure'], 'update_structure accepts an empty string for plain ?p=123 links' );

// category_base/tag_base omitted -> left untouched
$GLOBALS['_options']['category_base'] = 'kept-base';
$resp = imperal_rewrite_bridge_update_structure( new WP_REST_Request( array( 'permalink_structure' => '/%postname%/' ) ) );
assert_eq( 'kept-base', $resp['category_base'], 'update_structure leaves category_base untouched when omitted from the request' );

$resp = imperal_rewrite_bridge_update_structure( new WP_REST_Request() );
assert_true( is_wp_error( $resp ), 'update_structure without permalink_structure at all is a WP_Error' );
assert_eq( 400, $resp->get_status(), 'update_structure missing-field error is 400' );

// ─────────── flush ───────────

$wp_rewrite->flush_count = 0;
$GLOBALS['_options']['rewrite_rules'] = array();
$resp = imperal_rewrite_bridge_flush( new WP_REST_Request() );
assert_eq( true, $resp['flushed'], 'flush reports flushed=true' );
assert_eq( 1, $wp_rewrite->flush_count, 'flush actually calls WP_Rewrite::flush_rules()' );
assert_eq( 2, $resp['rule_count'], 'flush reports the resulting rule_count from the freshly-flushed rewrite_rules option' );

// ─────────── list_rules ───────────

$GLOBALS['_options']['rewrite_rules'] = array(
	'^wp-json/?$'                 => 'index.php?rest_route=/',
	'category/(.+?)/?$'           => 'index.php?category_name=$matches[1]',
);
$resp = imperal_rewrite_bridge_list_rules( new WP_REST_Request() );
assert_eq( 2, $resp['count'], 'list_rules counts every compiled rule' );
$matches = array_column( $resp['rules'], 'match' );
assert_true( in_array( '^wp-json/?$', $matches, true ), 'list_rules includes the wp-json rule' );
$wp_json_rule = current( array_filter( $resp['rules'], fn( $r ) => '^wp-json/?$' === $r['match'] ) );
assert_eq( 'index.php?rest_route=/', $wp_json_rule['query'], 'list_rules pairs each match with its own real query string, never fabricated' );

$GLOBALS['_options']['rewrite_rules'] = array();
$resp = imperal_rewrite_bridge_list_rules( new WP_REST_Request() );
assert_eq( 0, $resp['count'], 'list_rules reports 0 honestly when no rules are compiled yet' );

// ─────────── route registration ───────────

imperal_rewrite_bridge_register_routes();
foreach ( array(
	'imperal/v1/rewrite/structure',
	'imperal/v1/rewrite/flush',
	'imperal/v1/rewrite/rules',
) as $expected_route ) {
	assert_true( isset( $GLOBALS['_routes'][ $expected_route ] ), "route registered: $expected_route" );
}

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

<?php
/**
 * Standalone logic harness for imperal-builder-bridge.php.
 *
 * WordPress is not available here, so we stub the handful of core functions
 * the bridge touches and then exercise the pure logic: post resolution,
 * permission checks, active-builder detection, tree flattening for both
 * Elementor and Bricks, the state_token concurrency guard, and the update
 * flow for both builders.
 *
 * Run:  php tests/bridge_logic_test.php
 */

define( 'ABSPATH', __DIR__ );

$GLOBALS['_meta']    = array();   // post_id => [meta_key => raw value]
$GLOBALS['_posts']   = array();   // post_id => WP_Post
$GLOBALS['_caps']    = array();   // post_id => bool (can edit)
$GLOBALS['_routes']  = array();
$GLOBALS['_headers'] = array();

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

class FakeResponse {
	public $headers = array();
	public function header( $name, $value ) {
		$this->headers[ $name ] = $value;
	}
}

class WP_REST_Request {
	private $params;
	private $route;

	public function __construct( array $params = array(), $route = '/imperal/v1/builder' ) {
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

function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args;
}

function current_user_can( $cap, $id = null ) {
	if ( 'edit_posts' === $cap ) {
		return true;
	}
	return isset( $GLOBALS['_caps'][ $id ] ) ? $GLOBALS['_caps'][ $id ] : false;
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

function get_permalink( $post ) {
	return 'https://example.com/' . $post->post_name;
}

function sanitize_title( $value ) {
	return strtolower( trim( (string) $value ) );
}

function sanitize_key( $value ) {
	return strtolower( trim( (string) $value ) );
}

function get_post_meta( $id, $key, $single = false ) {
	if ( ! isset( $GLOBALS['_meta'][ $id ][ $key ] ) ) {
		return $single ? '' : array();
	}
	return $GLOBALS['_meta'][ $id ][ $key ];
}

function update_post_meta( $id, $key, $value ) {
	$GLOBALS['_meta'][ $id ][ $key ] = $value;
	return true;
}

function delete_post_meta( $id, $key ) {
	unset( $GLOBALS['_meta'][ $id ][ $key ] );
	return true;
}

function wp_json_encode( $data ) {
	return json_encode( $data );
}

function wp_slash( $value ) {
	return $value;
}

// ── Load the plugin ──────────────────────────────────────────────────────────

require __DIR__ . '/../imperal-builder-bridge.php';

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
	$GLOBALS['_meta']  = array();
	$GLOBALS['_posts'] = array();
	$GLOBALS['_caps']  = array();
}

function seed_post( $id, $slug, $type = 'page', $can_edit = true ) {
	$GLOBALS['_posts'][ $id ] = new WP_Post( $id, $slug, $type );
	$GLOBALS['_caps'][ $id ]  = $can_edit;
}

// ── Fixtures ─────────────────────────────────────────────────────────────────

function elementor_fixture() {
	return wp_json_encode( array(
		array(
			'id'       => 'sec1',
			'elType'   => 'section',
			'settings' => array( 'background_color' => '#fff' ),
			'elements' => array(
				array(
					'id'       => 'col1',
					'elType'   => 'column',
					'settings' => array(),
					'elements' => array(
						array(
							'id'         => 'w1',
							'elType'     => 'widget',
							'widgetType' => 'heading',
							'settings'   => array( 'title' => 'Old Title' ),
							'elements'   => array(),
						),
					),
				),
			),
		),
	) );
}

function bricks_fixture() {
	return wp_json_encode( array(
		array(
			'id'       => 'brx1',
			'name'     => 'container',
			'parent'   => 0,
			'settings' => array(),
			'label'    => '',
		),
		array(
			'id'       => 'brx2',
			'name'     => 'heading',
			'parent'   => 'brx1',
			'settings' => array( 'text' => 'Old Bricks Heading' ),
			'label'    => 'Heading',
		),
	) );
}

echo "\nimperal-builder-bridge logic tests\n\n";

echo "post resolution\n";
reset_state();
seed_post( 10, 'about', 'page' );
$post = imperal_builder_bridge_resolve_post( new WP_REST_Request( array( 'id' => 10 ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'resolves by id' );

$post = imperal_builder_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about' ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'resolves by slug' );

$err = imperal_builder_bridge_resolve_post( new WP_REST_Request( array() ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'no id and no slug is 400' );

$err = imperal_builder_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'nope' ) ) );
ok( is_wp_error( $err ) && 404 === $err->get_status(), 'unknown slug is 404' );

seed_post( 11, 'about', 'post' );
$err = imperal_builder_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about' ) ) );
ok( is_wp_error( $err ) && 409 === $err->get_status(), 'ambiguous slug is 409' );

$post = imperal_builder_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about', 'type' => 'page' ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'type disambiguates the slug' );

echo "\npermissions\n";
reset_state();
seed_post( 20, 'secret', 'page', false );
$res = imperal_builder_bridge_permission( new WP_REST_Request( array( 'id' => 20 ) ) );
ok( is_wp_error( $res ) && 403 === $res->get_status(), 'user without edit_post is refused' );

seed_post( 21, 'mine', 'page', true );
eq( imperal_builder_bridge_permission( new WP_REST_Request( array( 'id' => 21 ) ) ), true, 'user with edit_post allowed' );

echo "\nactive builder detection\n";
reset_state();
seed_post( 30, 'plain', 'page' );
eq( imperal_builder_bridge_active_builders( 30 ), array(), 'no builder meta means no active builder' );

$GLOBALS['_meta'][30]['_elementor_data'] = elementor_fixture();
eq( imperal_builder_bridge_active_builders( 30 ), array( 'elementor' ), 'elementor data marks elementor active' );

reset_state();
seed_post( 31, 'brx', 'page' );
$GLOBALS['_meta'][31]['_bricks_page_content_2'] = bricks_fixture();
eq( imperal_builder_bridge_active_builders( 31 ), array( 'bricks' ), 'bricks content zone marks bricks active' );

$GLOBALS['_meta'][31]['_elementor_data'] = elementor_fixture();
eq( imperal_builder_bridge_active_builders( 31 ), array( 'elementor', 'bricks' ), 'both builders can be active at once' );

echo "\nelementor: flattening\n";
$decoded = json_decode( elementor_fixture(), true );
$flat    = imperal_builder_bridge_flatten_elementor( $decoded );
eq( count( $flat ), 3, 'flattens nested tree into 3 rows' );
eq( $flat[0]['id'], 'sec1', 'root section first' );
eq( $flat[0]['parent_id'], null, 'root has no parent' );
eq( $flat[1]['id'], 'col1', 'column second' );
eq( $flat[1]['parent_id'], 'sec1', 'column parent is the section' );
eq( $flat[2]['id'], 'w1', 'widget third' );
eq( $flat[2]['parent_id'], 'col1', 'widget parent is the column' );
eq( $flat[2]['widget_type'], 'heading', 'widget_type carried for widgets' );
eq( $flat[2]['settings']['title'], 'Old Title', 'settings carried verbatim' );

echo "\nbricks: flattening\n";
$decoded = json_decode( bricks_fixture(), true );
$flat    = imperal_builder_bridge_flatten_bricks( $decoded, 'content' );
eq( count( $flat ), 2, 'flattens flat bricks array into 2 rows' );
eq( $flat[0]['parent_id'], null, 'parent 0 becomes null' );
eq( $flat[1]['parent_id'], 'brx1', 'child parent id carried as string' );
eq( $flat[1]['el_type'], 'heading', 'name maps to el_type' );
eq( $flat[1]['settings']['text'], 'Old Bricks Heading', 'settings carried verbatim' );
eq( $flat[1]['zone'], 'content', 'zone is stamped on each row' );

echo "\nstate_token\n";
$raw1 = elementor_fixture();
$raw2 = bricks_fixture();
ok( imperal_builder_bridge_state_token( $raw1 ) !== imperal_builder_bridge_state_token( $raw2 ), 'different content hashes differently' );
eq( imperal_builder_bridge_state_token( $raw1 ), imperal_builder_bridge_state_token( $raw1 ), 'same content hashes the same' );

echo "\nGET /builder\n";
reset_state();
seed_post( 40, 'page40', 'page' );
$GLOBALS['_meta'][40]['_elementor_data'] = elementor_fixture();
$res = imperal_builder_bridge_get_tree( new WP_REST_Request( array( 'id' => 40 ) ) );
ok( ! is_wp_error( $res ), 'reading a post with elementor content succeeds' );
eq( $res['active_builders'], array( 'elementor' ), 'reports elementor as active' );
eq( $res['builders']['elementor']['element_count'], 3, 'reports element count' );
ok( '' !== $res['builders']['elementor']['state_token'], 'state_token is present' );

reset_state();
seed_post( 41, 'page41', 'page' );
$res = imperal_builder_bridge_get_tree( new WP_REST_Request( array( 'id' => 41 ) ) );
ok( is_wp_error( $res ) && 404 === $res->get_status(), 'no builder content on the post is a 404' );

reset_state();
seed_post( 42, 'page42', 'page' );
$GLOBALS['_meta'][42]['_elementor_data'] = elementor_fixture();
$res = imperal_builder_bridge_get_tree( new WP_REST_Request( array( 'id' => 42, 'builder' => 'bricks' ) ) );
ok( is_wp_error( $res ) && 404 === $res->get_status(), 'requesting an inactive builder is a 404' );

echo "\nPOST /builder/field — elementor\n";
reset_state();
seed_post( 50, 'page50', 'page' );
$raw = elementor_fixture();
$GLOBALS['_meta'][50]['_elementor_data'] = $raw;
$token = imperal_builder_bridge_state_token( $raw );

$res = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id'          => 50,
	'element_id'  => 'w1',
	'field'       => 'title',
	'value'       => 'New Title',
	'state_token' => $token,
) ) );
ok( ! is_wp_error( $res ), 'updating an existing elementor field succeeds' );
eq( $res['builder'], 'elementor', 'reports builder=elementor' );

$decoded = json_decode( $GLOBALS['_meta'][50]['_elementor_data'], true );
$flat    = imperal_builder_bridge_flatten_elementor( $decoded );
$w1      = null;
foreach ( $flat as $row ) {
	if ( 'w1' === $row['id'] ) {
		$w1 = $row;
	}
}
eq( $w1['settings']['title'], 'New Title', 'the field is actually updated in stored meta' );
eq( $w1['id'], 'w1', 'the rest of the tree is untouched — same element still there' );
ok( count( $flat ) === 3, 'element count unchanged after a point edit' );

$res = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id'          => 50,
	'element_id'  => 'w1',
	'field'       => 'title',
	'value'       => 'Stale write attempt',
	'state_token' => $token, // stale — the real token changed after the update above
) ) );
ok( is_wp_error( $res ) && 409 === $res->get_status(), 'stale state_token is rejected with 409' );

$fresh_token = imperal_builder_bridge_state_token( $GLOBALS['_meta'][50]['_elementor_data'] );
$res = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id'          => 50,
	'element_id'  => 'nope',
	'field'       => 'title',
	'value'       => 'x',
	'state_token' => $fresh_token,
) ) );
ok( is_wp_error( $res ) && 404 === $res->get_status(), 'unknown element_id is a 404' );

echo "\nPOST /builder/field — bricks\n";
reset_state();
seed_post( 60, 'page60', 'page' );
$raw = bricks_fixture();
$GLOBALS['_meta'][60]['_bricks_page_content_2'] = $raw;
$token = imperal_builder_bridge_state_token( $raw );

$err = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id'          => 60,
	'element_id'  => 'brx2',
	'field'       => 'text',
	'value'       => 'New Bricks Heading',
	'state_token' => $token,
) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'bricks write without zone is a 400' );

$res = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id'          => 60,
	'element_id'  => 'brx2',
	'field'       => 'text',
	'value'       => 'New Bricks Heading',
	'state_token' => $token,
	'zone'        => 'content',
) ) );
ok( ! is_wp_error( $res ), 'updating an existing bricks field with zone succeeds' );

$decoded = json_decode( $GLOBALS['_meta'][60]['_bricks_page_content_2'], true );
$flat    = imperal_builder_bridge_flatten_bricks( $decoded, 'content' );
$brx2    = null;
foreach ( $flat as $row ) {
	if ( 'brx2' === $row['id'] ) {
		$brx2 = $row;
	}
}
eq( $brx2['settings']['text'], 'New Bricks Heading', 'the bricks field is actually updated' );

echo "\nrequired-field validation\n";
reset_state();
seed_post( 70, 'page70', 'page' );
$GLOBALS['_meta'][70]['_elementor_data'] = elementor_fixture();
$err = imperal_builder_bridge_update_field( new WP_REST_Request( array( 'id' => 70, 'field' => 'x', 'value' => 'y', 'state_token' => 'z' ) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'missing element_id is 400' );

$err = imperal_builder_bridge_update_field( new WP_REST_Request( array( 'id' => 70, 'element_id' => 'w1', 'value' => 'y', 'state_token' => 'z' ) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'missing field is 400' );

$err = imperal_builder_bridge_update_field( new WP_REST_Request( array( 'id' => 70, 'element_id' => 'w1', 'field' => 'title', 'state_token' => 'z' ) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'missing value is 400' );

$err = imperal_builder_bridge_update_field( new WP_REST_Request( array( 'id' => 70, 'element_id' => 'w1', 'field' => 'title', 'value' => 'y' ) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'missing state_token is 400' );

echo "\nambiguous builder\n";
reset_state();
seed_post( 80, 'page80', 'page' );
$GLOBALS['_meta'][80]['_elementor_data']         = elementor_fixture();
$GLOBALS['_meta'][80]['_bricks_page_content_2']  = bricks_fixture();
$err = imperal_builder_bridge_update_field( new WP_REST_Request( array(
	'id' => 80, 'element_id' => 'w1', 'field' => 'title', 'value' => 'x', 'state_token' => 'z',
) ) );
ok( is_wp_error( $err ) && 409 === $err->get_status(), 'both builders active with no builder param disambiguating is a 409' );

echo "\nstatus endpoint\n";
$status = imperal_builder_bridge_status();
eq( $status['bridge'], true, 'reports bridge present' );
eq( $status['elementor_active'], false, 'reports elementor absent when constant undefined' );
eq( $status['bricks_active'], false, 'reports bricks absent when constant/function undefined' );

echo "\nroutes\n";
imperal_builder_bridge_register_routes();
ok( isset( $GLOBALS['_routes']['imperal/v1/builder'] ), 'registers /imperal/v1/builder' );
ok( isset( $GLOBALS['_routes']['imperal/v1/builder/field'] ), 'registers /imperal/v1/builder/field' );
ok( isset( $GLOBALS['_routes']['imperal/v1/builder/status'] ), 'registers /imperal/v1/builder/status' );

// ── Summary ──────────────────────────────────────────────────────────────────

printf( "\n%d passed, %d failed\n\n", $GLOBALS['_pass'], $GLOBALS['_fail'] );
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

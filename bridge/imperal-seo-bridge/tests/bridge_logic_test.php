<?php
/**
 * Standalone logic harness for imperal-seo-bridge.php.
 *
 * WordPress is not available here, so we stub the handful of core functions
 * the bridge touches and then exercise the pure logic: sanitising, robots
 * normalisation/validation, slug resolution and the update flow.
 *
 * Run:  php tests/bridge_logic_test.php
 */

// ── Minimal WordPress stubs ──────────────────────────────────────────────────

define( 'ABSPATH', __DIR__ );

$GLOBALS['_meta']        = array();   // post_id => [key => value]
$GLOBALS['_posts']       = array();   // post_id => WP_Post
$GLOBALS['_caps']        = array();   // post_id => bool (can edit)
$GLOBALS['_filters']     = array();
$GLOBALS['_actions']     = array();
$GLOBALS['_routes']      = array();

class WP_Post {
	public $ID;
	public $post_name;
	public $post_type;
	public $post_status;
	public $post_title;

	public function __construct( $id, $name, $type, $status = 'publish', $title = '' ) {
		$this->ID          = $id;
		$this->post_name   = $name;
		$this->post_type   = $type;
		$this->post_status = $status;
		$this->post_title  = $title;
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
	$GLOBALS['_actions'][ $hook ][] = $cb;
}

function add_filter( $hook, $cb, $priority = 10, $args = 1 ) {
	$GLOBALS['_filters'][ $hook ][] = $cb;
}

function apply_filters( $hook, $value ) {
	return $value;
}

function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args;
}

function register_post_meta( $type, $key, $args ) {
	$GLOBALS['_registered'][ $type ][ $key ] = $args;
	return true;
}

function get_post_types( $args = array(), $output = 'names' ) {
	return array( 'post', 'page', 'product', 'attachment' );
}

function post_type_supports( $type, $feature ) {
	// attachment deliberately lacks custom-fields, product has it.
	if ( 'attachment' === $type ) {
		return false;
	}
	return true;
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

function get_permalink( $post ) {
	return 'https://example.com/' . $post->post_name;
}

function get_the_title( $post ) {
	return $post->post_title;
}

function get_posts( $args ) {
	$out = array();
	foreach ( $GLOBALS['_posts'] as $p ) {
		if ( $p->post_name !== $args['name'] ) {
			continue;
		}
		if ( ! in_array( $p->post_type, (array) $args['post_type'], true ) ) {
			continue;
		}
		$out[] = $p;
	}
	return $out;
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

function wp_filter_nohtml_kses( $value ) {
	return trim( strip_tags( (string) $value ) );
}

function esc_url_raw( $value ) {
	$value = trim( (string) $value );
	if ( '' === $value ) {
		return '';
	}
	return filter_var( $value, FILTER_VALIDATE_URL ) ? $value : '';
}

// ── Load the plugin ──────────────────────────────────────────────────────────

require __DIR__ . '/../imperal-seo-bridge.php';

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
		$label .= sprintf(
			'  (got %s, expected %s)',
			var_export( $actual, true ),
			var_export( $expected, true )
		);
	}
	ok( $same, $label );
}

function reset_state() {
	$GLOBALS['_meta']  = array();
	$GLOBALS['_posts'] = array();
	$GLOBALS['_caps']  = array();
}

function seed_post( $id, $slug, $type = 'post', $can_edit = true, $title = 'Hello' ) {
	$GLOBALS['_posts'][ $id ] = new WP_Post( $id, $slug, $type, 'publish', $title );
	$GLOBALS['_caps'][ $id ]  = $can_edit;
}

// ── Tests ────────────────────────────────────────────────────────────────────

echo "\nimperal-seo-bridge logic tests\n\n";

echo "post types\n";
$types = imperal_seo_bridge_post_types();
ok( in_array( 'post', $types, true ), 'covers post' );
ok( in_array( 'page', $types, true ), 'covers page (the bug in the old bridge)' );
ok( in_array( 'product', $types, true ), 'covers custom post types with custom-fields' );
ok( ! in_array( 'attachment', $types, true ), 'skips attachment' );

echo "\nmeta registration\n";
$GLOBALS['_registered'] = array();
imperal_seo_bridge_register_meta();
ok( isset( $GLOBALS['_registered']['page']['rank_math_title'] ), 'registers rank_math_title for pages' );
ok( isset( $GLOBALS['_registered']['page']['rank_math_description'] ), 'registers rank_math_description for pages' );
ok( ! isset( $GLOBALS['_registered']['post']['rank_math_robots'] ), 'does NOT register robots as collection meta (array-schema risk)' );
eq( $GLOBALS['_registered']['post']['rank_math_title']['type'], 'string', 'title registered as string' );

echo "\nsanitising (mirrors Rank Math Sanitize)\n";
eq( imperal_seo_bridge_sanitize( 'text', '<b>Hi</b> there' ), 'Hi there', 'strips html from text' );
eq( imperal_seo_bridge_sanitize( 'url', 'https://x.com/a' ), 'https://x.com/a', 'keeps valid url' );
eq( imperal_seo_bridge_sanitize( 'url', 'not a url' ), '', 'rejects invalid url' );
eq( imperal_seo_bridge_sanitize( 'text', array( 'a' ) ), '', 'non-scalar becomes empty' );

echo "\nrobots normalisation\n";
reset_state();
seed_post( 1, 'hello' );
$GLOBALS['_meta'][1]['rank_math_robots'] = array( 'noindex', 'nofollow' );
eq( imperal_seo_bridge_get_robots( 1 ), array( 'noindex', 'nofollow' ), 'reads array robots' );

$GLOBALS['_meta'][1]['rank_math_robots'] = 'noindex';
eq( imperal_seo_bridge_get_robots( 1 ), array( 'noindex' ), 'legacy scalar row becomes array' );

$GLOBALS['_meta'][1]['rank_math_robots'] = array( 'noindex', 'bogus', 'noindex' );
eq( imperal_seo_bridge_get_robots( 1 ), array( 'noindex' ), 'drops unknown values and dedupes' );

unset( $GLOBALS['_meta'][1]['rank_math_robots'] );
eq( imperal_seo_bridge_get_robots( 1 ), array(), 'missing robots is empty array, not null' );

echo "\nresolution by id and slug\n";
reset_state();
seed_post( 10, 'about', 'page' );
$post = imperal_seo_bridge_resolve_post( new WP_REST_Request( array( 'id' => 10 ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'resolves by id' );

$post = imperal_seo_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about' ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'resolves a page by slug' );

$err = imperal_seo_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'nope' ) ) );
ok( is_wp_error( $err ) && 404 === $err->get_status(), 'unknown slug is 404' );

$err = imperal_seo_bridge_resolve_post( new WP_REST_Request( array() ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'no id and no slug is 400' );

seed_post( 11, 'about', 'post' ); // same slug, different type
$err = imperal_seo_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about' ) ) );
ok( is_wp_error( $err ) && 409 === $err->get_status(), 'ambiguous slug is 409, never a silent wrong pick' );

$post = imperal_seo_bridge_resolve_post( new WP_REST_Request( array( 'slug' => 'about', 'type' => 'page' ) ) );
ok( $post instanceof WP_Post && 10 === $post->ID, 'type disambiguates the slug' );

echo "\npermissions\n";
reset_state();
seed_post( 20, 'secret', 'post', false );
$res = imperal_seo_bridge_read_permission( new WP_REST_Request( array( 'id' => 20 ) ) );
ok( is_wp_error( $res ) && 403 === $res->get_status(), 'user without edit_post is refused' );

seed_post( 21, 'mine', 'post', true );
eq( imperal_seo_bridge_read_permission( new WP_REST_Request( array( 'id' => 21 ) ) ), true, 'user with edit_post allowed' );

echo "\nreading empty meta (graceful fallback)\n";
reset_state();
seed_post( 30, 'blank', 'page', true, 'Blank Page' );
$payload = imperal_seo_bridge_get_meta( new WP_REST_Request( array( 'id' => 30 ) ) );
eq( $payload['meta_title'], '', 'missing meta_title is empty string' );
eq( $payload['meta_description'], '', 'missing meta_description is empty string' );
eq( $payload['robots'], array(), 'missing robots is empty array' );
eq( $payload['post_title'], 'Blank Page', 'still returns the real post title for context' );
eq( $payload['type'], 'page', 'reports the post type' );

echo "\nupdating\n";
reset_state();
seed_post( 40, 'target', 'page' );
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 40, 'meta_title' => 'New Title', 'meta_description' => 'New Desc' ) )
);
eq( $payload['meta_title'], 'New Title', 'writes meta_title' );
eq( $payload['meta_description'], 'New Desc', 'writes meta_description' );
eq( $payload['updated'], array( 'meta_title', 'meta_description' ), 'reports which fields changed' );

// Partial update must not wipe the other field.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 40, 'meta_description' => 'Only Desc' ) )
);
eq( $payload['meta_title'], 'New Title', 'partial update leaves meta_title intact' );
eq( $payload['meta_description'], 'Only Desc', 'partial update changes meta_description' );

// Empty string clears the row.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 40, 'meta_title' => '' ) )
);
eq( $payload['meta_title'], '', 'empty value clears the meta' );
ok( ! isset( $GLOBALS['_meta'][40]['rank_math_title'] ), 'cleared meta row is deleted, not stored blank' );

// HTML is stripped on write.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 40, 'meta_title' => '<script>x</script>Clean' ) )
);
eq( $payload['meta_title'], 'xClean', 'html stripped on write' );

echo "\nrobots writing\n";
reset_state();
seed_post( 50, 'robots', 'post' );
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 50, 'robots' => array( 'noindex', 'nofollow' ) ) )
);
eq( $payload['robots'], array( 'noindex', 'nofollow' ), 'writes robots array' );

$err = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 50, 'robots' => array( 'bogus' ) ) )
);
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'unknown robots value rejected with 400' );

$err = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 50, 'robots' => 'noindex' ) )
);
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'non-array robots rejected' );

$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 50, 'robots' => array() ) )
);
eq( $payload['robots'], array(), 'empty robots array clears the setting' );

echo "\ncanonical\n";
reset_state();
seed_post( 60, 'canon', 'post' );
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 60, 'canonical_url' => 'https://example.com/real' ) )
);
eq( $payload['canonical_url'], 'https://example.com/real', 'writes canonical url' );

$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 60, 'canonical_url' => 'garbage' ) )
);
eq( $payload['canonical_url'], '', 'invalid canonical is rejected to empty, never stored raw' );

echo "\nno-op guard\n";
reset_state();
seed_post( 70, 'noop', 'post' );
$err = imperal_seo_bridge_update_meta( new WP_REST_Request( array( 'id' => 70 ) ) );
ok( is_wp_error( $err ) && 400 === $err->get_status(), 'update with no SEO fields is an explicit error' );

echo "\nstatus endpoint\n";
$status = imperal_seo_bridge_status();
eq( $status['bridge'], true, 'reports bridge present' );
eq( $status['rank_math_active'], false, 'reports Rank Math absent when constant undefined' );
ok( in_array( 'page', $status['post_types'], true ), 'status lists covered post types' );
eq( $status['robots_choices'], array( 'index', 'noindex', 'nofollow', 'noarchive', 'noimageindex', 'nosnippet' ), 'status lists Rank Math robots choices' );

echo "\nroutes\n";
imperal_seo_bridge_register_routes();
ok( isset( $GLOBALS['_routes']['imperal/v1/seo'] ), 'registers /imperal/v1/seo' );
ok( isset( $GLOBALS['_routes']['imperal/v1/seo/status'] ), 'registers /imperal/v1/seo/status' );

// ── Summary ──────────────────────────────────────────────────────────────────

printf( "\n%d passed, %d failed\n\n", $GLOBALS['_pass'], $GLOBALS['_fail'] );
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

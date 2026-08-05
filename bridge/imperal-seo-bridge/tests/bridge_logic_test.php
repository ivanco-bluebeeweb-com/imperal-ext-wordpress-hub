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
$GLOBALS['_terms']       = array();   // term_id => WP_Term
$GLOBALS['_caps']        = array();   // post_id => bool (can edit)
$GLOBALS['_term_caps']   = array();   // term_id => bool (can edit term)
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

class WP_Term {
	public $term_id;
	public $slug;
	public $taxonomy;
	public $name;

	public function __construct( $id, $slug, $taxonomy = 'category', $name = '' ) {
		$this->term_id  = $id;
		$this->slug     = $slug;
		$this->taxonomy = $taxonomy;
		$this->name     = $name;
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
	private $route;

	public function __construct( array $params = array(), $route = '/imperal/v1/seo' ) {
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

// Record fired actions and cache-header calls so the no-cache guard is testable.
function do_action( $hook ) {
	$GLOBALS['_fired'][] = $hook;
}

function nocache_headers() {
	$GLOBALS['_nocache_headers'] = ( $GLOBALS['_nocache_headers'] ?? 0 ) + 1;
}

function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args;
}

function register_post_meta( $type, $key, $args ) {
	$GLOBALS['_registered'][ $type ][ $key ] = $args;
	return true;
}

function register_term_meta( $taxonomy, $key, $args ) {
	$GLOBALS['_registered_term'][ $taxonomy ][ $key ] = $args;
	return true;
}

function get_taxonomies( $args = array(), $output = 'names' ) {
	return array( 'category', 'post_tag', 'nav_menu', 'wp_pattern_category', 'product_cat' );
}

function get_term( $id, $taxonomy = '' ) {
	if ( ! isset( $GLOBALS['_terms'][ $id ] ) ) {
		return null;
	}
	$term = $GLOBALS['_terms'][ $id ];
	if ( '' !== $taxonomy && $term->taxonomy !== $taxonomy ) {
		return null;
	}
	return $term;
}

function get_terms( $args ) {
	$out = array();
	foreach ( $GLOBALS['_terms'] as $t ) {
		if ( isset( $args['slug'] ) && $t->slug !== $args['slug'] ) {
			continue;
		}
		if ( isset( $args['taxonomy'] ) && ! in_array( $t->taxonomy, (array) $args['taxonomy'], true ) ) {
			continue;
		}
		$out[] = $t;
	}
	return $out;
}

function get_term_link( $term ) {
	return 'https://example.com/category/' . $term->slug . '/';
}

function get_term_meta( $id, $key, $single = false ) {
	$store = 'term:' . $id;
	if ( ! isset( $GLOBALS['_meta'][ $store ][ $key ] ) ) {
		return $single ? '' : array();
	}
	return $GLOBALS['_meta'][ $store ][ $key ];
}

function update_term_meta( $id, $key, $value ) {
	$GLOBALS['_meta'][ 'term:' . $id ][ $key ] = $value;
	return true;
}

function delete_term_meta( $id, $key ) {
	unset( $GLOBALS['_meta'][ 'term:' . $id ][ $key ] );
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
	if ( 'edit_term' === $cap ) {
		// Kept in its own map so a term test can never pass via edit_posts.
		return isset( $GLOBALS['_term_caps'][ $id ] ) ? $GLOBALS['_term_caps'][ $id ] : false;
	}
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

echo "\nrich snippet (schema type)\n";
reset_state();
seed_post( 80, 'schema-post', 'post' );
$payload = imperal_seo_bridge_get_meta( new WP_REST_Request( array( 'id' => 80 ) ) );
eq( $payload['rich_snippet'], '', 'missing rich_snippet reads as empty string, not an error' );

$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'rich_snippet' => 'Article' ) )
);
eq( $payload['rich_snippet'], 'Article', 'writes rich_snippet' );
eq( $payload['updated'], array( 'rich_snippet' ), 'reports rich_snippet as the changed field' );
eq( $GLOBALS['_meta'][80]['rank_math_rich_snippet'], 'Article', 'stored under the real rank_math_rich_snippet key' );

// Rank Math's own "no schema" state.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'rich_snippet' => 'off' ) )
);
eq( $payload['rich_snippet'], 'off', "'off' (Rank Math's disabled state) is stored as a normal value, not treated as empty" );

// Partial update must not disturb rich_snippet, and vice versa.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'rich_snippet' => 'Product' ) )
);
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'meta_title' => 'Unrelated change' ) )
);
eq( $payload['rich_snippet'], 'Product', 'updating another field leaves rich_snippet intact' );

// HTML is stripped on write, same as title/description.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'rich_snippet' => '<script>x</script>Book' ) )
);
eq( $payload['rich_snippet'], 'xBook', 'html stripped on write, same treatment as title/description' );

// Empty string clears the row like every other string field.
$payload = imperal_seo_bridge_update_meta(
	new WP_REST_Request( array( 'id' => 80, 'rich_snippet' => '' ) )
);
eq( $payload['rich_snippet'], '', 'empty value clears rich_snippet' );
ok( ! isset( $GLOBALS['_meta'][80]['rank_math_rich_snippet'] ), 'cleared rich_snippet row is deleted, not stored blank' );

// Terms get the same field under the same key, isolated from post meta.
reset_state();
seed_post( 81, 'schema-post-2', 'post' );
$GLOBALS['_terms'][9] = new WP_Term( 9, 'schema-term', 'category', 'Schema Term' );
$GLOBALS['_term_caps'][9] = true;
$term_payload = imperal_seo_bridge_update_term_meta_route(
	new WP_REST_Request( array( 'id' => 9, 'rich_snippet' => 'FAQPage' ) )
);
eq( $term_payload['rich_snippet'], 'FAQPage', 'writes rich_snippet on a TERM' );
eq( $GLOBALS['_meta'][9]['rank_math_rich_snippet'] ?? null, null, 'term write does not leak into post meta store' );

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

echo "\nno-cache guard\n";
// Regression: LiteSpeed cached a permission-gated response on a live site and
// replayed it to an anonymous caller (x-litespeed-cache: hit, HTTP 200 with
// real SEO data; the same request with a cache-buster correctly gave 403).
$GLOBALS['_fired']           = array();
$GLOBALS['_nocache_headers'] = 0;

// A route from another plugin must be left completely alone.
$passthru = imperal_seo_bridge_no_cache( 'untouched', null, new WP_REST_Request( array(), '/wp/v2/posts' ) );
eq( $passthru, 'untouched', 'foreign namespace: result passes through unchanged' );
eq( $GLOBALS['_nocache_headers'], 0, 'foreign namespace: no cache headers sent' );
ok( ! in_array( 'litespeed_control_set_nocache', $GLOBALS['_fired'], true ), 'foreign namespace: LiteSpeed switch not touched' );

// Our own route must be marked uncacheable.
$result = imperal_seo_bridge_no_cache( 'payload', null, new WP_REST_Request( array( 'id' => 1 ), '/imperal/v1/seo' ) );
eq( $result, 'payload', 'own route: result passes through unchanged' );
eq( $GLOBALS['_nocache_headers'], 1, 'own route: nocache_headers() called' );
ok( in_array( 'litespeed_control_set_nocache', $GLOBALS['_fired'], true ), 'own route: LiteSpeed no-cache switch fired' );
ok( defined( 'DONOTCACHEPAGE' ) && DONOTCACHEPAGE, 'own route: DONOTCACHEPAGE defined for page caches' );

// The status route is equally per-user and must be covered too.
$GLOBALS['_fired'] = array();
imperal_seo_bridge_no_cache( null, null, new WP_REST_Request( array(), '/imperal/v1/seo/status' ) );
ok( in_array( 'litespeed_control_set_nocache', $GLOBALS['_fired'], true ), 'status route is also marked no-cache' );

// A non-request argument must not blow up the whole REST stack.
$safe = imperal_seo_bridge_no_cache( 'x', null, null );
eq( $safe, 'x', 'non-request argument is ignored safely' );

// ── Term (category) SEO meta ─────────────────────────────────────────────────

echo "\nterms: registration\n";

$GLOBALS['_registered_term'] = array();
imperal_seo_bridge_register_term_meta();

ok( isset( $GLOBALS['_registered_term']['category']['rank_math_title'] ), 'category gets rank_math_title registered' );
ok( isset( $GLOBALS['_registered_term']['category']['rank_math_description'] ), 'category gets rank_math_description registered' );
ok( isset( $GLOBALS['_registered_term']['product_cat']['rank_math_title'] ), 'custom taxonomy is covered too' );
ok( ! isset( $GLOBALS['_registered_term']['nav_menu'] ), 'nav_menu is skipped — menus carry no SEO meaning' );
ok( ! isset( $GLOBALS['_registered_term']['wp_pattern_category'] ), 'wp_pattern_category is skipped' );
ok( ! in_array( 'nav_menu', imperal_seo_bridge_taxonomies(), true ), 'taxonomy list excludes nav_menu' );

// Registered term meta must be writable only by someone who can edit THAT term.
$auth = $GLOBALS['_registered_term']['category']['rank_math_title']['auth_callback'];
$GLOBALS['_term_caps'] = array( 7 => true, 8 => false );
ok( true === $auth( false, 'rank_math_title', 7 ), 'auth_callback allows a user who can edit that term' );
ok( false === $auth( true, 'rank_math_title', 8 ), 'auth_callback denies a user who cannot edit that term' );

// Term meta must be sanitised on the way in, exactly like post meta.
$san = $GLOBALS['_registered_term']['category']['rank_math_title']['sanitize_callback'];
eq( $san( '<b>Bold</b> title' ), 'Bold title', 'term title sanitiser strips markup' );
$san_url = $GLOBALS['_registered_term']['category']['rank_math_canonical_url']['sanitize_callback'];
eq( $san_url( 'javascript:alert(1)' ), '', 'term canonical rejects a non-http scheme' );

echo "\nterms: read\n";

$GLOBALS['_terms'] = array(
	11 => new WP_Term( 11, 'sisteme', 'category', 'Sisteme' ),
	12 => new WP_Term( 12, 'alegere', 'category', 'Alegere' ),
	13 => new WP_Term( 13, 'sisteme', 'product_cat', 'Sisteme (produse)' ),
);
$GLOBALS['_term_caps'] = array( 11 => true, 12 => true, 13 => true );
$GLOBALS['_meta']['term:11'] = array(
	'rank_math_title'       => 'Existing term title',
	'rank_math_description' => 'Existing term description',
	'rank_math_robots'      => array( 'index', 'nofollow' ),
);

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'id' => 11 ) ) );
ok( ! is_wp_error( $res ), 'reading a term by id succeeds' );
eq( $res['meta_title'], 'Existing term title', 'term meta_title is read from rank_math_title' );
eq( $res['meta_description'], 'Existing term description', 'term meta_description is read from rank_math_description' );
eq( $res['robots'], array( 'index', 'nofollow' ), 'term robots come back as an array' );

// The payload must speak the SAME key names as the post payload, because the
// Python client reads `id`/`type`. A bridge that renamed them would silently
// degrade every read to id 0 / empty type — that exact bug shipped once.
eq( $res['id'], 11, 'term payload uses `id`, like the post payload' );
eq( $res['type'], 'category', 'term payload puts the taxonomy in `type`' );
eq( $res['taxonomy'], 'category', 'term payload also exposes `taxonomy` explicitly' );
eq( $res['slug'], 'sisteme', 'term payload carries the slug' );
eq( $res['post_title'], 'Sisteme', 'term payload puts the term name in `post_title`' );
ok( '' !== $res['link'], 'term payload carries a link' );

$post_keys = array_keys( imperal_seo_bridge_payload( new WP_Post( 1, 'x', 'post', 'publish', 'X' ) ) );
$term_keys = array_keys( imperal_seo_bridge_term_payload( $GLOBALS['_terms'][11] ) );
ok( ! array_diff( $post_keys, $term_keys ), 'term payload is a superset of the post payload keys' );

// A term with no SEO meta at all is normal, not an error.
$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'id' => 12 ) ) );
eq( $res['meta_title'], '', 'a term with no SEO meta reads as empty, not an error' );
eq( $res['robots'], array(), 'missing robots reads as an empty array' );

// Slug resolution, including the refusal to guess.
$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'slug' => 'alegere' ) ) );
eq( $res['id'], 12, 'a unique slug resolves' );

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'slug' => 'sisteme' ) ) );
ok( is_wp_error( $res ), 'a slug used by two taxonomies is refused, never guessed' );
eq( $res->get_error_code(), 'imperal_seo_ambiguous_slug', 'ambiguous term slug returns the ambiguous code' );
eq( $res->get_status(), 409, 'ambiguous term slug is a 409' );

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'slug' => 'sisteme', 'taxonomy' => 'product_cat' ) ) );
eq( $res['id'], 13, 'passing the taxonomy disambiguates the slug' );

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'slug' => 'sisteme', 'type' => 'product_cat' ) ) );
eq( $res['id'], 13, '`type` works as an alias of `taxonomy`' );

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array( 'id' => 999 ) ) );
ok( is_wp_error( $res ) && 404 === $res->get_status(), 'unknown term id is a 404' );

$res = imperal_seo_bridge_get_term_meta_route( new WP_REST_Request( array() ) );
ok( is_wp_error( $res ) && 400 === $res->get_status(), 'no id and no slug is a 400' );

echo "\nterms: permission\n";

$GLOBALS['_term_caps'] = array( 11 => false, 12 => true );
$res = imperal_seo_bridge_term_permission( new WP_REST_Request( array( 'id' => 11 ) ) );
ok( is_wp_error( $res ), 'a user who cannot edit that term is refused' );
eq( $res->get_status(), 403, 'refusal is a 403' );
ok( true === imperal_seo_bridge_term_permission( new WP_REST_Request( array( 'id' => 12 ) ) ), 'a user who can edit that term is allowed' );
ok( false === imperal_seo_bridge_can_edit_term( 0 ), 'term id 0 can never be edited' );
ok( false === imperal_seo_bridge_can_edit_term( -5 ), 'a negative term id can never be edited' );

echo "\nterms: write\n";

$GLOBALS['_term_caps']       = array( 11 => true );
$GLOBALS['_meta']['term:11'] = array();

$res = imperal_seo_bridge_update_term_meta_route(
	new WP_REST_Request(
		array(
			'id'               => 11,
			'meta_title'       => 'Ventilație și climatizare | G4S',
			'meta_description' => 'Cum funcționează sistemele inginerești.',
		)
	)
);
ok( ! is_wp_error( $res ), 'writing term SEO meta succeeds' );
eq( $GLOBALS['_meta']['term:11']['rank_math_title'], 'Ventilație și climatizare | G4S', 'title lands in rank_math_title on the TERM' );
eq( $GLOBALS['_meta']['term:11']['rank_math_description'], 'Cum funcționează sistemele inginerești.', 'description lands in rank_math_description on the TERM' );
eq( $res['updated_fields'], array( 'meta_title', 'meta_description' ), 'only the supplied fields are reported' );
ok( ! isset( $GLOBALS['_meta'][11] ), 'term write does NOT leak into post meta' );

// A partial update must not wipe the other fields.
imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'meta_description' => 'Doar descrierea.' ) ) );
eq( $GLOBALS['_meta']['term:11']['rank_math_title'], 'Ventilație și climatizare | G4S', 'updating description leaves the title intact' );

// An explicitly empty value must DELETE the row, so Rank Math falls back to its
// template instead of rendering an empty tag.
imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'meta_title' => '' ) ) );
ok( ! isset( $GLOBALS['_meta']['term:11']['rank_math_title'] ), 'an empty title deletes the row rather than storing empty' );

// Markup and bad URLs are sanitised on the write path too.
// strip_tags removes the tags and keeps their inner text, so the assertion
// mirrors the post-side test rather than pretending inner text disappears.
imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'meta_title' => '<b>Curat</b>' ) ) );
eq( $GLOBALS['_meta']['term:11']['rank_math_title'], 'Curat', 'markup is stripped before storage' );

$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'canonical_url' => 'https://g4s.md/category/sisteme/' ) ) );
eq( $GLOBALS['_meta']['term:11']['rank_math_canonical_url'], 'https://g4s.md/category/sisteme/', 'a valid canonical is stored' );

// robots: valid values become a real array; junk is rejected with a 400.
$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'robots' => array( 'noindex', 'noindex', 'nofollow' ) ) ) );
eq( $GLOBALS['_meta']['term:11']['rank_math_robots'], array( 'noindex', 'nofollow' ), 'robots is stored as a deduped array' );
ok( is_array( $GLOBALS['_meta']['term:11']['rank_math_robots'] ), 'robots is stored as an ARRAY, as Rank Math expects' );

$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'robots' => array( 'nonsense' ) ) ) );
ok( is_wp_error( $res ) && 400 === $res->get_status(), 'an unknown robots value is rejected' );

$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'robots' => 'noindex' ) ) );
ok( is_wp_error( $res ) && 400 === $res->get_status(), 'a scalar robots value is rejected' );

$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11, 'robots' => array() ) ) );
ok( ! isset( $GLOBALS['_meta']['term:11']['rank_math_robots'] ), 'an empty robots array clears the row' );

$res = imperal_seo_bridge_update_term_meta_route( new WP_REST_Request( array( 'id' => 11 ) ) );
ok( is_wp_error( $res ) && 400 === $res->get_status(), 'a term update with no SEO fields is an explicit error' );

// Legacy scalar robots rows must still read back as an array.
$GLOBALS['_meta']['term:11']['rank_math_robots'] = 'noindex';
eq( imperal_seo_bridge_get_term_robots( 11 ), array( 'noindex' ), 'a legacy scalar robots row reads back as an array' );

echo "\nterms: routes and status\n";

$GLOBALS['_routes'] = array();
imperal_seo_bridge_register_routes();
ok( isset( $GLOBALS['_routes']['imperal/v1/seo/term'] ), 'the term route is registered' );
$term_route = $GLOBALS['_routes']['imperal/v1/seo/term'];
eq( $term_route[0]['permission_callback'], 'imperal_seo_bridge_term_permission', 'term GET is permission-gated' );
eq( $term_route[1]['permission_callback'], 'imperal_seo_bridge_term_permission', 'term POST is permission-gated' );
ok( isset( $GLOBALS['_routes']['imperal/v1/seo'] ), 'the post route still exists — no regression' );

$status = imperal_seo_bridge_status();
ok( isset( $status['taxonomies'] ), 'status reports the covered taxonomies' );
ok( in_array( 'category', $status['taxonomies'], true ), 'status lists category as covered' );
eq( $status['bridge_version'], IMPERAL_SEO_BRIDGE_VERSION, 'status reports the bridge version' );

// The no-cache guard must cover the term route too — it is per-user as well.
$GLOBALS['_fired'] = array();
imperal_seo_bridge_no_cache( null, null, new WP_REST_Request( array( 'id' => 11 ), '/imperal/v1/seo/term' ) );
ok( in_array( 'litespeed_control_set_nocache', $GLOBALS['_fired'], true ), 'term route is marked no-cache' );

// ── Summary ──────────────────────────────────────────────────────────────────

printf( "\n%d passed, %d failed\n\n", $GLOBALS['_pass'], $GLOBALS['_fail'] );
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

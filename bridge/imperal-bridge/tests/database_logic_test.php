<?php
/**
 * Standalone logic harness for the DATABASE section (SECTION 12) of
 * imperal-bridge.php: search-replace (including the serialized-value-safe
 * recursive replacer), table-name/wildcard resolution scoped to this site's
 * own $wpdb->prefix, and the plain read paths (list tables, post-count,
 * orphaned postmeta).
 *
 * WordPress/MySQL are not available here, so a minimal fake $wpdb models
 * just the query shapes SECTION 12 actually issues: DESCRIBE, a paginated
 * SELECT of primary key + text columns, UPDATE by primary key, SHOW TABLES
 * LIKE, information_schema.tables, SHOW CREATE TABLE, and the two plain
 * COUNT(*) queries. This is intentionally NOT a general SQL engine -- it is
 * a fixture that answers exactly the queries this section's own code sends,
 * the same "logic harness, not a SQL engine" bar as builder/media/seo's own
 * fakes for get_post_meta()/wpdb-free calls.
 *
 * Run:  php tests/database_logic_test.php
 */

define( 'ABSPATH', __DIR__ . '/' );
define( 'DB_NAME', 'wordpress' );

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
	$GLOBALS['_actions'][ $hook ][] = $cb;
}

function add_filter( $hook, $cb, $priority = 10, $args = 1 ) {
	// no-op: other sections in the required file register filters we don't exercise here.
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

/**
 * Minimal fake $wpdb -- answers exactly the query shapes SECTION 12 sends
 * against an in-memory table model, and implements ->prepare()/->esc_like()/
 * ->_real_escape()/->update() closely enough for the logic under test.
 */
class FakeWpdb {
	public $prefix = 'wp_';
	public $posts = 'wp_posts';
	public $postmeta = 'wp_postmeta';
	/** @var array<string, array<string,string>> table => [column => mysql type] */
	public $schemas = array();
	/** @var array<string, array<int, array<string,mixed>>> table => rows (each row assoc array) */
	public $data = array();
	/** @var array<string, string> table => primary key column name */
	public $pk = array();
	public $update_calls = array();

	public function prepare( $query, ...$args ) {
		// Only %s/%d substitution is needed by this section's own queries.
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

	public function _real_escape( $v ) {
		return addslashes( (string) $v );
	}

	private function table_from_backticked( $sql ) {
		if ( preg_match( '/(?:FROM|TABLE)\s+`([a-zA-Z0-9_]+)`/i', $sql, $m ) ) {
			return $m[1];
		}
		preg_match( '/`([a-zA-Z0-9_]+)`/', $sql, $m );
		return $m[1] ?? '';
	}

	public function get_col( $sql ) {
		// SHOW TABLES LIKE '<prefix>%' -- return every table whose name
		// starts with the prefix baked into the LIKE pattern.
		if ( preg_match( "/LIKE '([^']*)'/", $sql, $m ) ) {
			$like = str_replace( array( '\\_', '\\%' ), array( '_', '%' ), $m[1] );
			$pattern = '/^' . str_replace( '%', '.*', preg_quote( rtrim( $like, '%' ), '/' ) ) . '.*$/';
			return array_values( array_filter( array_keys( $this->data ), function ( $t ) use ( $pattern ) {
				return preg_match( $pattern, $t );
			} ) );
		}
		return array();
	}

	public function get_results( $sql, $output = OBJECT ) {
		if ( 0 === strpos( $sql, 'DESCRIBE' ) ) {
			$table = $this->table_from_backticked( $sql );
			$out   = array();
			foreach ( $this->schemas[ $table ] ?? array() as $col => $type ) {
				$out[] = (object) array(
					'Field' => $col,
					'Type'  => $type,
					'Key'   => ( $col === ( $this->pk[ $table ] ?? '' ) ) ? 'PRI' : '',
				);
			}
			return $out;
		}
		if ( false !== strpos( $sql, 'FROM `' ) && false !== strpos( $sql, 'LIMIT' ) ) {
			$table = $this->table_from_backticked( $sql );
			preg_match( '/LIMIT (\d+) OFFSET (\d+)/', $sql, $m );
			$limit  = (int) ( $m[1] ?? 500 );
			$offset = (int) ( $m[2] ?? 0 );
			$rows   = array_slice( $this->data[ $table ] ?? array(), $offset, $limit );
			if ( ARRAY_A === $output ) {
				return $rows;
			}
			return array_map( function ( $r ) { return (object) $r; }, $rows );
		}
		if ( false !== strpos( $sql, 'information_schema.tables' ) ) {
			$out = array();
			foreach ( $this->data as $table => $rows ) {
				$out[] = (object) array( 'name' => $table, 'bytes' => 1048576.0 );
			}
			return $out;
		}
		if ( 0 === strpos( $sql, 'SELECT * FROM `' ) ) {
			$table = $this->table_from_backticked( $sql );
			$rows  = $this->data[ $table ] ?? array();
			if ( ARRAY_A === $output ) {
				return $rows;
			}
			return array_map( function ( $r ) { return (object) $r; }, $rows );
		}
		return array();
	}

	public function get_row( $sql, $output = OBJECT ) {
		if ( 0 === strpos( $sql, 'OPTIMIZE TABLE' ) || 0 === strpos( $sql, 'CHECK TABLE' ) || 0 === strpos( $sql, 'REPAIR TABLE' ) ) {
			return array( 'Msg_text' => 'OK' );
		}
		if ( 0 === strpos( $sql, 'SHOW CREATE TABLE' ) ) {
			$table = $this->table_from_backticked( $sql );
			return array( 0 => $table, 1 => "CREATE TABLE `{$table}` (...)" );
		}
		if ( false !== strpos( $sql, 'information_schema.tables' ) ) {
			$bytes = 0;
			foreach ( $this->data as $rows ) {
				$bytes += 1048576;
			}
			return (object) array( 'bytes' => (float) $bytes );
		}
		return null;
	}

	public function get_var( $sql ) {
		if ( false !== strpos( $sql, 'wp_posts' ) && false !== strpos( $sql, 'post_type' ) ) {
			preg_match( "/post_type = '([^']*)'/", $sql, $m );
			$post_type = $m[1] ?? '';
			$count     = 0;
			foreach ( $this->data['wp_posts'] ?? array() as $row ) {
				if ( ( $row['post_type'] ?? '' ) === $post_type ) {
					$count++;
				}
			}
			return $count;
		}
		if ( false !== strpos( $sql, 'LEFT JOIN' ) ) {
			$post_ids = array_column( $this->data['wp_posts'] ?? array(), 'ID' );
			$orphaned = 0;
			foreach ( $this->data['wp_postmeta'] ?? array() as $row ) {
				if ( ! in_array( $row['post_id'], $post_ids, true ) ) {
					$orphaned++;
				}
			}
			return $orphaned;
		}
		return 0;
	}

	public function update( $table, $data, $where ) {
		$this->update_calls[] = array( $table, $data, $where );
		foreach ( $this->data[ $table ] as &$row ) {
			$match = true;
			foreach ( $where as $k => $v ) {
				if ( $row[ $k ] !== $v ) {
					$match = false;
					break;
				}
			}
			if ( $match ) {
				foreach ( $data as $k => $v ) {
					$row[ $k ] = $v;
				}
			}
		}
		unset( $row );
		return 1;
	}
}

if ( ! defined( 'OBJECT' ) ) {
	define( 'OBJECT', 'OBJECT' );
}
if ( ! defined( 'ARRAY_A' ) ) {
	define( 'ARRAY_A', 'ARRAY_A' );
}
if ( ! defined( 'ARRAY_N' ) ) {
	define( 'ARRAY_N', 'ARRAY_N' );
}

/**
 * WordPress core's real is_serialized()/serialize()/unserialize() ARE plain
 * PHP built-ins (serialize/unserialize) plus one small core helper we must
 * stub, since core itself isn't loaded here.
 */
function is_serialized( $data, $strict = true ) {
	if ( ! is_string( $data ) ) {
		return false;
	}
	$data = trim( $data );
	if ( 'N;' === $data ) {
		return true;
	}
	if ( strlen( $data ) < 4 || ':' !== $data[1] ) {
		return false;
	}
	if ( $strict ) {
		$lastc = substr( $data, -1 );
		if ( ';' !== $lastc && '}' !== $lastc ) {
			return false;
		}
	}
	$token = $data[0];
	switch ( $token ) {
		case 's':
			if ( $strict && '"' !== substr( $data, -2, 1 ) ) {
				return false;
			}
		case 'a':
		case 'O':
		case 'b':
		case 'i':
		case 'd':
			return true;
	}
	return false;
}

$GLOBALS['wpdb'] = new FakeWpdb();
global $wpdb;
$wpdb = $GLOBALS['wpdb'];

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

function reset_wpdb() {
	global $wpdb;
	$wpdb = new FakeWpdb();
	$GLOBALS['wpdb'] = $wpdb;
}

// ── Tests: recursive serialized-value-safe replace ───────────────────────────

$count = 0;
$plain = imperal_database_bridge_recursive_replace( 'https://staging.example.com/x', 'staging.example.com', 'example.com', $count );
eq( $plain, 'https://example.com/x', 'plain string replace works' );
eq( $count, 1, 'plain string replace counts 1 occurrence' );

$count      = 0;
$serialized = serialize( array( 'url' => 'https://staging.example.com/a', 'nested' => array( 'u' => 'https://staging.example.com/b' ) ) );
$after      = imperal_database_bridge_recursive_replace( $serialized, 'staging.example.com', 'example.com', $count );
eq( $count, 2, 'both occurrences inside a serialized array are counted' );
$unserialized_after = unserialize( $after );
eq( $unserialized_after['url'], 'https://example.com/a', 'serialized value is correctly RE-serialized, not string-mangled (outer key)' );
eq( $unserialized_after['nested']['u'], 'https://example.com/b', 'serialized value correctly re-serialized (nested key)' );
ok( is_serialized( $after, false ), 'the output is still valid serialized PHP after replace (length prefixes intact)' );

$count = 0;
$false_serialized = 'b:0;';
$after2            = imperal_database_bridge_recursive_replace( $false_serialized, 'staging.example.com', 'example.com', $count );
eq( $after2, 'b:0;', 'a serialized `false` scalar (b:0;) is preserved untouched, not mistaken for a non-serialized string' );

$count = 0;
$no_match = imperal_database_bridge_recursive_replace( 'nothing to see here', 'staging.example.com', 'example.com', $count );
eq( $count, 0, 'no occurrences -> count stays 0' );
eq( $no_match, 'nothing to see here', 'no occurrences -> value unchanged' );

// ── Tests: own-table discovery + wildcard resolution ─────────────────────────

reset_wpdb();
$wpdb->data = array(
	'wp_posts'    => array(),
	'wp_postmeta' => array(),
	'wp_options'  => array(),
	'other_site_table' => array(),
);

$own = imperal_database_bridge_own_tables();
sort( $own );
eq( $own, array( 'wp_options', 'wp_postmeta', 'wp_posts' ), 'own_tables() returns only this prefix\'s tables, never another site\'s table in a shared DB' );

$resolved = imperal_database_bridge_resolve_tables( null );
sort( $resolved );
eq( $resolved, array( 'wp_options', 'wp_postmeta', 'wp_posts' ), 'resolve_tables(null) -> every own table' );

$resolved = imperal_database_bridge_resolve_tables( array( 'wp_post*' ) );
sort( $resolved );
eq( $resolved, array( 'wp_postmeta', 'wp_posts' ), 'wildcard "wp_post*" expands to the matching own tables' );

$resolved = imperal_database_bridge_resolve_tables( array( 'other_site_table' ) );
ok( is_wp_error( $resolved ) && 'imperal_db_unknown_table' === $resolved->get_error_code(), 'a table outside this prefix is refused, never touched' );

$resolved = imperal_database_bridge_resolve_tables( array( 'DROP TABLE wp_posts' ) );
ok( is_wp_error( $resolved ) && 'imperal_db_bad_table' === $resolved->get_error_code(), 'a non-identifier-shaped table name is rejected outright' );

// ── Tests: search-replace end-to-end (dry-run never writes, apply does) ──────

reset_wpdb();
$wpdb->schemas['wp_options'] = array( 'option_id' => 'bigint', 'option_name' => 'varchar(191)', 'option_value' => 'longtext' );
$wpdb->pk['wp_options']      = 'option_id';
$wpdb->data['wp_options']    = array(
	array( 'option_id' => 1, 'option_name' => 'siteurl', 'option_value' => 'https://staging.example.com' ),
	array( 'option_id' => 2, 'option_name' => 'home', 'option_value' => 'https://staging.example.com' ),
	array( 'option_id' => 3, 'option_name' => 'blogname', 'option_value' => 'My Site' ),
);

$dry_req = new WP_REST_Request( array( 'old' => 'staging.example.com', 'new' => 'example.com', 'dry_run' => true ) );
$dry_res = imperal_database_bridge_search_replace( $dry_req );
eq( $dry_res['dry_run'], true, 'dry_run flag echoed back' );
eq( $dry_res['replacements'], 2, 'dry-run reports the correct replacement count' );
eq( $wpdb->data['wp_options'][0]['option_value'], 'https://staging.example.com', 'dry-run NEVER writes -- row 1 unchanged' );
eq( count( $wpdb->update_calls ), 0, 'dry-run issues zero UPDATE calls' );

$apply_req = new WP_REST_Request( array( 'old' => 'staging.example.com', 'new' => 'example.com', 'dry_run' => false ) );
$apply_res = imperal_database_bridge_search_replace( $apply_req );
eq( $apply_res['replacements'], 2, 'apply reports the same replacement count as the preview' );
eq( $wpdb->data['wp_options'][0]['option_value'], 'https://example.com', 'apply actually writes the replacement' );
eq( $wpdb->data['wp_options'][1]['option_value'], 'https://example.com', 'apply writes every matching row, not just the first' );
eq( $wpdb->data['wp_options'][2]['option_value'], 'My Site', 'a row with no match is left untouched' );
eq( count( $wpdb->update_calls ), 2, 'apply issues one UPDATE per changed row, not per column/table' );

$empty_req = new WP_REST_Request( array( 'old' => '', 'new' => 'example.com' ) );
$empty_res = imperal_database_bridge_search_replace( $empty_req );
ok( is_wp_error( $empty_res ) && 'imperal_db_bad_params' === $empty_res->get_error_code(), 'empty old is rejected before touching the database' );

// ── Tests: plain read paths ──────────────────────────────────────────────────

reset_wpdb();
$wpdb->data = array( 'wp_posts' => array(), 'wp_postmeta' => array() );
$tables_res = imperal_database_bridge_list_tables();
eq( count( $tables_res['tables'] ), 2, 'list_tables returns one entry per own table' );
ok( false !== strpos( $tables_res['tables'][0]['size'], 'MB' ), 'table size is formatted with an MB suffix' );

reset_wpdb();
$wpdb->data['wp_posts'] = array(
	array( 'ID' => 1, 'post_type' => 'post' ),
	array( 'ID' => 2, 'post_type' => 'post' ),
	array( 'ID' => 3, 'post_type' => 'page' ),
);
$count_res = imperal_database_bridge_post_count( new WP_REST_Request( array( 'post_type' => 'post' ) ) );
eq( $count_res['count'], 2, 'post_count counts only the requested post_type' );

$bad_count_res = imperal_database_bridge_post_count( new WP_REST_Request( array( 'post_type' => '' ) ) );
ok( is_wp_error( $bad_count_res ) && 'imperal_db_bad_params' === $bad_count_res->get_error_code(), 'post_count rejects an empty post_type' );

reset_wpdb();
$wpdb->data['wp_posts']    = array( array( 'ID' => 1, 'post_type' => 'post' ) );
$wpdb->data['wp_postmeta'] = array(
	array( 'post_id' => 1, 'meta_key' => 'a', 'meta_value' => 'x' ),
	array( 'post_id' => 999, 'meta_key' => 'b', 'meta_value' => 'y' ), // orphaned: post 999 doesn't exist
);
$orphan_res = imperal_database_bridge_orphaned_postmeta();
eq( $orphan_res['orphaned_postmeta'], 1, 'orphaned_postmeta counts rows whose post no longer exists' );

// ── Tests: routes registered ─────────────────────────────────────────────────

imperal_database_bridge_register_routes();
foreach ( array( 'search-replace', 'tables', 'optimize', 'check', 'export', 'post-count', 'orphaned-postmeta' ) as $slug ) {
	ok( isset( $GLOBALS['_routes'][ "imperal/v1/database/{$slug}" ] ), "route registered: /database/{$slug}" );
}

// ── Summary ───────────────────────────────────────────────────────────────────

echo "\n" . $GLOBALS['_pass'] . " passed, " . $GLOBALS['_fail'] . " failed\n";
exit( $GLOBALS['_fail'] > 0 ? 1 : 0 );

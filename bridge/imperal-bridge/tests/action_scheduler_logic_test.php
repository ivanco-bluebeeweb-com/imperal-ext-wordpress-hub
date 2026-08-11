<?php
/**
 * Standalone logic harness for the ACTION SCHEDULER section (SECTION 16) of
 * imperal-bridge.php: list/get/run/cancel/retry scheduled actions + status
 * counts, against a FAKE in-memory ActionScheduler/ActionScheduler_Store
 * (the real Action Scheduler needs WooCommerce + MySQL -- out of scope for
 * a logic-only harness with no network/DB access). No real
 * WordPress/MySQL/network needed.
 *
 * Run:  php tests/action_scheduler_logic_test.php
 */

define( 'ABSPATH', __DIR__ . '/' );

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

$GLOBALS['_routes'] = array();
function register_rest_route( $ns, $route, $args ) {
	$GLOBALS['_routes'][ $ns . $route ] = $args[0];
}

// ─────────────────────── fake Action Scheduler ───────────────────────

class ActionScheduler_Store {
	const STATUS_COMPLETE = 'complete';
	const STATUS_PENDING  = 'pending';
	const STATUS_RUNNING  = 'in-progress';
	const STATUS_FAILED   = 'failed';
	const STATUS_CANCELED = 'canceled';

	/** @var array<int,array> id => [hook, args, group, status, scheduled] */
	public $actions = array();

	public function fetch_action( $action_id ) {
		if ( ! isset( $this->actions[ $action_id ] ) ) {
			return new FakeAction( '', array(), '', null );
		}
		$a = $this->actions[ $action_id ];
		return new FakeAction( $a['hook'], $a['args'], $a['group'], $a['scheduled'] );
	}

	public function get_status( $action_id ) {
		return isset( $this->actions[ $action_id ] ) ? $this->actions[ $action_id ]['status'] : '';
	}

	public function cancel_action( $action_id ) {
		if ( isset( $this->actions[ $action_id ] ) ) {
			$this->actions[ $action_id ]['status'] = self::STATUS_CANCELED;
		}
	}

	public function action_counts() {
		$counts = array();
		foreach ( $this->actions as $a ) {
			$counts[ $a['status'] ] = ( $counts[ $a['status'] ] ?? 0 ) + 1;
		}
		return $counts;
	}

	public function add( $hook, $args, $group, $status ) {
		$id                    = count( $this->actions ) + 1;
		$this->actions[ $id ] = array(
			'hook'      => $hook,
			'args'      => $args,
			'group'     => $group,
			'status'    => $status,
			'scheduled' => time(),
		);
		return $id;
	}
}

class FakeSchedule {
	private $date;
	public function __construct( $timestamp ) {
		$this->date = $timestamp ? new FakeDate( $timestamp ) : null;
	}
	public function get_date() {
		return $this->date;
	}
}

class FakeDate {
	private $timestamp;
	public function __construct( $timestamp ) {
		$this->timestamp = $timestamp;
	}
	public function format( $fmt ) {
		return (string) $this->timestamp;
	}
}

class FakeAction {
	private $hook;
	private $args;
	private $group;
	private $schedule;

	public function __construct( $hook, $args, $group, $scheduled ) {
		$this->hook     = $hook;
		$this->args     = $args;
		$this->group    = $group;
		$this->schedule = new FakeSchedule( $scheduled );
	}

	public function get_hook() {
		return $this->hook;
	}
	public function get_args() {
		return $this->args;
	}
	public function get_group() {
		return $this->group;
	}
	public function get_schedule() {
		return $this->schedule;
	}
}

class FakeLogEntry {
	private $message;
	private $date;
	public function __construct( $message, $timestamp ) {
		$this->message = $message;
		$this->date    = new FakeDate( $timestamp );
	}
	public function get_message() {
		return $this->message;
	}
	public function get_date() {
		return $this->date;
	}
}

class ActionScheduler_Logger {
	/** @var array<int,array> */
	public $logs = array();

	public function get_logs( $action_id ) {
		$out = array();
		foreach ( $this->logs[ $action_id ] ?? array() as $l ) {
			$out[] = new FakeLogEntry( $l['message'], $l['date'] );
		}
		return $out;
	}
}

class ActionScheduler_Runner {
	/** @var array<int> */
	public $processed = array();
	/** @var Exception|null */
	public $throw_on_next = null;

	public function process_action( $action_id, $context = '' ) {
		$this->processed[] = $action_id;
		if ( $this->throw_on_next ) {
			$e                   = $this->throw_on_next;
			$this->throw_on_next = null;
			throw $e;
		}
	}
}

class ActionScheduler {
	public static $store_instance  = null;
	public static $logger_instance = null;
	public static $runner_instance = null;

	public static function store() {
		return self::$store_instance;
	}
	public static function logger() {
		return self::$logger_instance;
	}
	public static function runner() {
		return self::$runner_instance;
	}
}

$GLOBALS['_as_enqueued'] = array();
function as_enqueue_async_action( $hook, $args = array(), $group = '' ) {
	$GLOBALS['_as_enqueued'][] = array( 'hook' => $hook, 'args' => $args, 'group' => $group );
	return ActionScheduler::store()->add( $hook, $args, $group, ActionScheduler_Store::STATUS_PENDING );
}

function as_get_scheduled_actions( $args, $return = 'ids' ) {
	$store = ActionScheduler::store();
	$ids   = array_keys( $store->actions );
	if ( isset( $args['status'] ) ) {
		$ids = array_values(
			array_filter(
				$ids,
				function ( $id ) use ( $store, $args ) {
					return $store->actions[ $id ]['status'] === $args['status'];
				}
			)
		);
	}
	if ( isset( $args['hook'] ) ) {
		$ids = array_values(
			array_filter(
				$ids,
				function ( $id ) use ( $store, $args ) {
					return $store->actions[ $id ]['hook'] === $args['hook'];
				}
			)
		);
	}
	if ( isset( $args['group'] ) ) {
		$ids = array_values(
			array_filter(
				$ids,
				function ( $id ) use ( $store, $args ) {
					return $store->actions[ $id ]['group'] === $args['group'];
				}
			)
		);
	}
	return $ids;
}

function reset_as_fixtures() {
	ActionScheduler::$store_instance  = new ActionScheduler_Store();
	ActionScheduler::$logger_instance = new ActionScheduler_Logger();
	ActionScheduler::$runner_instance = new ActionScheduler_Runner();
	$GLOBALS['_as_enqueued']          = array();
}

// Load the bridge file AFTER declaring ActionScheduler et al so
// `class_exists( 'ActionScheduler' )` sees our fakes, then also declare
// `as_get_scheduled_actions` before requiring so `function_exists()` passes.
reset_as_fixtures();

require __DIR__ . '/../imperal-bridge.php';
imperal_as_bridge_register_routes();

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

// ─────────── list_actions ───────────

reset_as_fixtures();
ActionScheduler::store()->add( 'woocommerce_deliver_webhook_async', array( 1 ), 'webhooks', ActionScheduler_Store::STATUS_PENDING );
ActionScheduler::store()->add( 'wc_admin_daily', array(), 'wc-admin', ActionScheduler_Store::STATUS_COMPLETE );
$req    = new WP_REST_Request();
$result = imperal_as_bridge_list_actions( $req );
assert_true( ! is_wp_error( $result ), 'list_actions succeeds' );
assert_true( 2 === $result['count'], 'list_actions returns both fixture actions' );

reset_as_fixtures();
ActionScheduler::store()->add( 'a_hook', array(), '', ActionScheduler_Store::STATUS_PENDING );
ActionScheduler::store()->add( 'b_hook', array(), '', ActionScheduler_Store::STATUS_FAILED );
$req    = new WP_REST_Request( array( 'status' => 'failed' ) );
$result = imperal_as_bridge_list_actions( $req );
assert_true( 1 === $result['count'], 'list_actions filters by status' );
assert_true( 'b_hook' === $result['actions'][0]['hook'], 'list_actions status filter returns the correct action' );

// ─────────── get_action ───────────

reset_as_fixtures();
$id     = ActionScheduler::store()->add( 'my_hook', array( 'x' => 1 ), 'my_group', ActionScheduler_Store::STATUS_COMPLETE );
ActionScheduler::logger()->logs[ $id ] = array( array( 'message' => 'action started', 'date' => time() ) );
$req    = new WP_REST_Request( array( 'id' => $id ) );
$result = imperal_as_bridge_get_action( $req );
assert_true( ! is_wp_error( $result ), 'get_action succeeds for a real action' );
assert_true( 'my_hook' === $result['hook'], 'get_action returns the correct hook' );
assert_true( 'my_group' === $result['group'], 'get_action returns the correct group' );
assert_true( 1 === count( $result['logs'] ), 'get_action includes its log entries' );

reset_as_fixtures();
$req    = new WP_REST_Request( array( 'id' => 999 ) );
$result = imperal_as_bridge_get_action( $req );
assert_true( is_wp_error( $result ), 'get_action rejects an unknown id' );
assert_true( 404 === $result->get_status(), 'get_action unknown-id status is 404' );

// ─────────── run_action ───────────

reset_as_fixtures();
$id     = ActionScheduler::store()->add( 'run_me', array(), '', ActionScheduler_Store::STATUS_PENDING );
$req    = new WP_REST_Request( array( 'id' => $id ) );
$result = imperal_as_bridge_run_action( $req );
assert_true( ! is_wp_error( $result ), 'run_action succeeds' );
assert_true( true === $result['ran'], 'run_action reports ran=true' );
assert_true( false === $result['failed'], 'run_action reports failed=false on success' );
assert_true( array( $id ) === ActionScheduler::runner()->processed, 'run_action actually called the runner with the correct id' );

reset_as_fixtures();
$id                                       = ActionScheduler::store()->add( 'blows_up', array(), '', ActionScheduler_Store::STATUS_PENDING );
ActionScheduler::runner()->throw_on_next = new Exception( 'callback exploded' );
$req                                      = new WP_REST_Request( array( 'id' => $id ) );
$result                                   = imperal_as_bridge_run_action( $req );
assert_true( ! is_wp_error( $result ), 'run_action still returns a normal response when the hook throws' );
assert_true( true === $result['failed'], 'run_action reports failed=true when the hook throws' );
assert_true( 'callback exploded' === $result['error'], 'run_action surfaces the real exception message' );

reset_as_fixtures();
$req    = new WP_REST_Request( array( 'id' => 999 ) );
$result = imperal_as_bridge_run_action( $req );
assert_true( is_wp_error( $result ), 'run_action rejects an unknown id' );

// ─────────── cancel_action ───────────

reset_as_fixtures();
$id     = ActionScheduler::store()->add( 'cancel_me', array(), '', ActionScheduler_Store::STATUS_PENDING );
$req    = new WP_REST_Request( array( 'id' => $id ) );
$result = imperal_as_bridge_cancel_action( $req );
assert_true( ! is_wp_error( $result ), 'cancel_action succeeds' );
assert_true( true === $result['cancelled'], 'cancel_action reports cancelled=true' );
assert_true( ActionScheduler_Store::STATUS_CANCELED === ActionScheduler::store()->get_status( $id ), 'cancel_action actually changed the stored status' );

reset_as_fixtures();
$req    = new WP_REST_Request( array( 'id' => 999 ) );
$result = imperal_as_bridge_cancel_action( $req );
assert_true( is_wp_error( $result ), 'cancel_action rejects an unknown id' );

// ─────────── retry_action ───────────

reset_as_fixtures();
$id     = ActionScheduler::store()->add( 'retry_me', array( 'y' => 2 ), 'retry_group', ActionScheduler_Store::STATUS_FAILED );
$req    = new WP_REST_Request( array( 'id' => $id ) );
$result = imperal_as_bridge_retry_action( $req );
assert_true( ! is_wp_error( $result ), 'retry_action succeeds for a failed action' );
assert_true( true === $result['retried'], 'retry_action reports retried=true' );
assert_true( $id === $result['original_id'], 'retry_action echoes the original id' );
assert_true( 'retry_me' === $result['new_action']['hook'], 'retry_action new action has the same hook' );
assert_true( 1 === count( $GLOBALS['_as_enqueued'] ), 'retry_action actually enqueued exactly one new async action' );

reset_as_fixtures();
$id     = ActionScheduler::store()->add( 'still_pending', array(), '', ActionScheduler_Store::STATUS_PENDING );
$req    = new WP_REST_Request( array( 'id' => $id ) );
$result = imperal_as_bridge_retry_action( $req );
assert_true( is_wp_error( $result ), 'retry_action rejects a non-failed action' );
assert_true( 400 === $result->get_status(), 'retry_action non-failed status is 400' );
assert_true( 0 === count( $GLOBALS['_as_enqueued'] ), 'retry_action never enqueues anything for a non-failed action' );

reset_as_fixtures();
$req    = new WP_REST_Request( array( 'id' => 999 ) );
$result = imperal_as_bridge_retry_action( $req );
assert_true( is_wp_error( $result ), 'retry_action rejects an unknown id' );
assert_true( 404 === $result->get_status(), 'retry_action unknown-id status is 404' );

// ─────────── counts ───────────

reset_as_fixtures();
ActionScheduler::store()->add( 'a', array(), '', ActionScheduler_Store::STATUS_PENDING );
ActionScheduler::store()->add( 'b', array(), '', ActionScheduler_Store::STATUS_PENDING );
ActionScheduler::store()->add( 'c', array(), '', ActionScheduler_Store::STATUS_FAILED );
$req    = new WP_REST_Request();
$result = imperal_as_bridge_counts( $req );
assert_true( ! is_wp_error( $result ), 'counts succeeds' );
assert_true( 2 === $result['counts'][ ActionScheduler_Store::STATUS_PENDING ], 'counts groups pending correctly' );
assert_true( 1 === $result['counts'][ ActionScheduler_Store::STATUS_FAILED ], 'counts groups failed correctly' );

// ─────────── route registration ───────────

assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/actions'] ), 'list actions route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/actions/(?P<id>\d+)'] ), 'get action route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/actions/(?P<id>\d+)/run'] ), 'run action route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/actions/(?P<id>\d+)/cancel'] ), 'cancel action route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/actions/(?P<id>\d+)/retry'] ), 'retry action route registered' );
assert_true( isset( $GLOBALS['_routes']['imperal/v1/action-scheduler/counts'] ), 'counts route registered' );
assert_true(
	WP_REST_Server::CREATABLE === $GLOBALS['_routes']['imperal/v1/action-scheduler/actions/(?P<id>\d+)/run']['methods'],
	'run action route is POST-only'
);

echo "\n$passed passed, $failed failed\n";
exit( $failed > 0 ? 1 : 0 );

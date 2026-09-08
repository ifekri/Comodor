/**
 * The parts of a Comodor client that are not about how it is drawn.
 *
 * A terminal and a desktop window disagree about almost everything except
 * what a session *is*: which message a delta belongs to, whose output a line
 * of tool text is, whether the mode the person is aiming at has been reached,
 * and whether the viewport is following the newest line. Those are decisions,
 * not pixels, and making them twice is how two clients end up disagreeing
 * about the same session.
 *
 * So they are here, with no renderer in sight and no dependency beyond the
 * protocol types and the mode cycle.
 */

export {
  canSubmit,
  initial,
  presented,
  presentedPermission,
  presentedQuestion,
  reduce,
  streaming,
  timeline,
  toolsOfTurn,
  unsent,
  waitingCount,
  type Action,
  type Connection,
  type Entry,
  type Interaction,
  type InteractionKind,
  type InteractionState,
  type Line,
  type MessageState,
  type Snapshot,
  type Speaker,
  type State,
  type ToolRun,
  type ToolState,
} from "./projection.ts";

export {
  begin as beginIntent,
  confirmed as intentConfirmed,
  due as intentDue,
  refuse as refuseIntent,
  sending as intentSending,
  settled as intentSettled,
  step as stepIntent,
  want as wantMode,
  type ModeIntent,
} from "./intent.ts";

export {
  grew,
  marker as followMarker,
  moved as followMoved,
  sent as followSent,
  start as followStart,
  tail as followTail,
  type Follow,
} from "./follow.ts";

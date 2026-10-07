//! When a crashed Core is started again (data-model.md §3, OD-1, FR-005).
//!
//! `RestartPolicy` counts consecutive crashes of a Core that had reached
//! `ready`. Crashes 1 and 2 restart it; crash 3 does not, and the window
//! waits for "Try again". Only a **completed** turn resets the count, under a
//! conservative rule: `Turns` watches what the relay read — the `session.send`
//! result's `turn_id`, `message.completed`, `session.updated` busy,
//! `notification.created` level and a relayed `session.cancel` — and calls a
//! turn completed only when it ended (`busy: false`) after at least one
//! completed message and nothing uncertain. Anything else leaves the count
//! as it was: "Try again", time, and every uncertain outcome.

use crate::relay::Observation;

/// The crash at which automatic restarts stop.
pub const LIMIT: u32 = 3;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RestartPolicy {
    count: u32,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        Self::new()
    }
}

impl RestartPolicy {
    pub fn new() -> Self {
        Self { count: 0 }
    }

    /// Consecutive crashes since the last completed turn.
    pub fn count(&self) -> u32 {
        self.count
    }

    /// A ready Core crashed. Whether to start it again automatically.
    pub fn crashed(&mut self) -> bool {
        self.count += 1;
        self.count < LIMIT
    }

    /// A turn completed: the count starts again.
    pub fn completed(&mut self) {
        self.count = 0;
    }
}

/// One turn the relay saw start.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TurnObservation {
    pub turn_id: String,
    pub completed_messages: u32,
    pub uncertain: bool,
}

/// The turns of the current Core, as far as the relay has seen them.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Turns {
    open: Vec<TurnObservation>,
}

impl Turns {
    pub fn new() -> Self {
        Self::default()
    }

    /// One thing the relay saw. True when it completed a turn.
    pub fn observe(&mut self, observation: &Observation) -> bool {
        match observation {
            Observation::TurnStarted(turn_id) => {
                self.open.push(TurnObservation { turn_id: turn_id.clone(), ..Default::default() });
                false
            }
            Observation::MessageCompleted { turn_id, completed } => {
                if let Some(turn) = self.open.iter_mut().find(|turn| &turn.turn_id == turn_id) {
                    if *completed {
                        turn.completed_messages += 1;
                    } else {
                        turn.uncertain = true;
                    }
                }
                false
            }
            // A warning or error, or a cancel the person sent, makes every
            // open turn uncertain: none of them can count as completed.
            Observation::Warning | Observation::Cancel => {
                self.open.iter_mut().for_each(|turn| turn.uncertain = true);
                false
            }
            Observation::Busy(true) => false,
            Observation::Busy(false) => {
                let completed = self.open.iter()
                    .any(|turn| turn.completed_messages >= 1 && !turn.uncertain);
                self.open.clear();
                completed
            }
        }
    }

    /// The Core is gone: whatever was open never completes.
    pub fn forget(&mut self) {
        self.open.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use Observation::*;

    fn completed(turn: &str) -> Observation {
        MessageCompleted { turn_id: turn.into(), completed: true }
    }

    fn ended(turn: &str, events: &[Observation]) -> bool {
        let mut turns = Turns::new();
        let mut done = turns.observe(&TurnStarted(turn.into()));
        for event in events {
            done |= turns.observe(event);
        }
        done
    }

    // -- the count ------------------------------------------------------------

    #[test]
    fn crashes_one_and_two_restart_and_crash_three_does_not() {
        let mut policy = RestartPolicy::new();
        assert!(policy.crashed());
        assert_eq!(policy.count(), 1);
        assert!(policy.crashed());
        assert_eq!(policy.count(), 2);
        assert!(!policy.crashed(), "the third crash waits for Try again");
        assert_eq!(policy.count(), 3);
        assert_eq!(LIMIT, 3);
    }

    #[test]
    fn after_the_limit_every_further_crash_waits_too() {
        let mut policy = RestartPolicy::new();
        for _ in 0..3 {
            policy.crashed();
        }
        // "Try again" starts a Core without touching the count, so the next
        // crash stops again.
        assert!(!policy.crashed());
        assert_eq!(policy.count(), 4);
    }

    #[test]
    fn only_a_completed_turn_resets_the_count() {
        let mut policy = RestartPolicy::new();
        policy.crashed();
        policy.crashed();
        policy.completed();
        assert_eq!(policy.count(), 0);
        assert!(policy.crashed());
    }

    // -- the conservative rule ------------------------------------------------

    #[test]
    fn a_turn_with_completed_messages_that_ends_with_nothing_uncertain_is_completed() {
        assert!(ended("t1", &[completed("t1"), completed("t1"), Busy(false)]));
    }

    #[test]
    fn a_turn_is_completed_only_when_it_ends() {
        let mut turns = Turns::new();
        turns.observe(&TurnStarted("t1".into()));
        assert!(!turns.observe(&completed("t1")));
        assert!(!turns.observe(&Busy(true)));
        assert!(turns.observe(&Busy(false)));
        assert!(!turns.observe(&Busy(false)), "a turn completes once");
    }

    #[test]
    fn a_cancelled_or_failed_message_is_uncertain() {
        assert!(!ended("t1", &[completed("t1"),
                               MessageCompleted { turn_id: "t1".into(), completed: false },
                               Busy(false)]));
    }

    #[test]
    fn a_warning_is_uncertain_cancel_between_messages_and_the_clarification_stop() {
        assert!(!ended("t1", &[completed("t1"), Warning, Busy(false)]));
    }

    #[test]
    fn an_error_notification_is_uncertain_a_failure_between_messages() {
        // The relay reads `warning` and `error` levels both as `Warning`.
        assert!(!ended("t1", &[completed("t1"), Warning, Busy(false)]));
    }

    #[test]
    fn a_relayed_cancel_is_uncertain() {
        assert!(!ended("t1", &[completed("t1"), Cancel, Busy(false)]));
    }

    #[test]
    fn zero_completed_messages_is_not_completed() {
        assert!(!ended("t1", &[Busy(false)]));
    }

    #[test]
    fn a_turn_the_relay_did_not_see_start_never_completes() {
        let mut turns = Turns::new();
        assert!(!turns.observe(&completed("t9")));
        assert!(!turns.observe(&Busy(false)));
    }

    #[test]
    fn messages_of_another_turn_do_not_count() {
        assert!(!ended("t1", &[completed("t2"), Busy(false)]));
    }

    #[test]
    fn a_crash_before_the_end_never_completes() {
        let mut turns = Turns::new();
        turns.observe(&TurnStarted("t1".into()));
        turns.observe(&completed("t1"));
        turns.forget();
        assert!(!turns.observe(&Busy(false)));
    }
}

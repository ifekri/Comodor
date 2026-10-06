//! Sleep and wake (spec: Machine sleep and wake).
//!
//! How long the machine has slept is read from two of the platform's clocks:
//! one that keeps running while the machine sleeps and one that does not.
//! Their difference grows only while it sleeps, so when it has grown, the
//! machine has woken since it was last looked at.

use std::sync::Mutex;
use std::time::Duration;

/// A sleep shorter than this is not a wake worth checking the Core for.
pub const THRESHOLD: Duration = Duration::from_secs(1);

/// How often the application looks, besides before every line the page
/// sends.
pub const POLL: Duration = Duration::from_secs(1);

/// Whether the machine has slept since it was last asked.
pub struct Watch {
    asleep: Box<dyn Fn() -> Option<Duration> + Send + Sync>,
    seen: Mutex<Option<Duration>>,
}

impl Watch {
    /// A watch over `asleep`: how long the machine has slept, from any fixed
    /// origin, or `None` where it cannot be read.
    pub fn new(asleep: Box<dyn Fn() -> Option<Duration> + Send + Sync>) -> Self {
        let seen = Mutex::new(asleep());
        Self { asleep, seen }
    }

    /// The watch over this platform's clocks.
    pub fn system() -> Self {
        Self::new(Box::new(slept))
    }

    /// True once for each sleep of at least `THRESHOLD` since the last time.
    pub fn woke(&self) -> bool {
        let Some(now) = (self.asleep)() else { return false };
        let mut seen = self.seen.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        match *seen {
            // Shorter sleeps add up: the mark moves only on a wake.
            Some(before) if now < before + THRESHOLD => false,
            Some(_) => {
                *seen = Some(now);
                true
            }
            None => {
                *seen = Some(now);
                false
            }
        }
    }
}

/// How long the machine has slept, from a fixed origin; `None` where the
/// clocks cannot be read. The clock that stops during sleep is read first,
/// so the difference never comes out short.
#[cfg(target_os = "linux")]
pub fn slept() -> Option<Duration> {
    // `CLOCK_MONOTONIC` stops while the machine is suspended; `CLOCK_BOOTTIME`
    // does not.
    let awake = clock(libc::CLOCK_MONOTONIC)?;
    clock(libc::CLOCK_BOOTTIME)?.checked_sub(awake)
}

#[cfg(target_os = "macos")]
pub fn slept() -> Option<Duration> {
    // `CLOCK_UPTIME_RAW` stops while the machine sleeps; `CLOCK_MONOTONIC_RAW`
    // does not. Both are unadjusted, so their difference moves only then.
    let awake = clock(libc::CLOCK_UPTIME_RAW)?;
    clock(libc::CLOCK_MONOTONIC_RAW)?.checked_sub(awake)
}

#[cfg(windows)]
pub fn slept() -> Option<Duration> {
    use windows_sys::Win32::System::WindowsProgramming::{QueryInterruptTime, QueryUnbiasedInterruptTime};
    // Both in 100 ns units; the unbiased one leaves out time spent asleep.
    let mut awake = 0u64;
    let mut total = 0u64;
    // SAFETY: each writes one u64 through a valid pointer.
    if unsafe { QueryUnbiasedInterruptTime(&mut awake) } == 0 {
        return None;
    }
    unsafe { QueryInterruptTime(&mut total) };
    total.checked_sub(awake).map(|units| Duration::from_nanos(units.saturating_mul(100)))
}

#[cfg(not(any(target_os = "linux", target_os = "macos", windows)))]
pub fn slept() -> Option<Duration> {
    None
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
fn clock(id: libc::clockid_t) -> Option<Duration> {
    let mut now = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: `clock_gettime` writes one timespec through a valid pointer.
    if unsafe { libc::clock_gettime(id, &mut now) } != 0 {
        return None;
    }
    Some(Duration::new(u64::try_from(now.tv_sec).ok()?, u32::try_from(now.tv_nsec).ok()?))
}

/// Look every `POLL` for as long as the application runs, and call `woke`
/// on each wake.
pub fn watch(watch: std::sync::Arc<Watch>, woke: impl Fn() + Send + 'static) {
    let _ = std::thread::Builder::new().name("wake-watch".into()).spawn(move || loop {
        std::thread::sleep(POLL);
        if watch.woke() {
            woke();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn watched(start: Duration) -> (Watch, Arc<Mutex<Option<Duration>>>) {
        let clock = Arc::new(Mutex::new(Some(start)));
        let reading = clock.clone();
        (Watch::new(Box::new(move || *reading.lock().unwrap())), clock)
    }

    fn sleep_for(clock: &Mutex<Option<Duration>>, by: Duration) {
        let mut now = clock.lock().unwrap();
        *now = now.map(|at| at + by);
    }

    #[test]
    fn a_sleep_is_seen_once_as_a_wake() {
        let (watch, clock) = watched(Duration::from_secs(5));
        assert!(!watch.woke(), "nothing slept yet");
        sleep_for(&clock, Duration::from_millis(300));
        assert!(!watch.woke(), "shorter than the threshold");
        sleep_for(&clock, Duration::from_secs(2));
        assert!(watch.woke(), "the machine slept");
        assert!(!watch.woke(), "the same sleep is seen once");
        sleep_for(&clock, Duration::from_secs(60));
        assert!(watch.woke(), "and the next one again");
    }

    #[test]
    fn short_sleeps_add_up() {
        let (watch, clock) = watched(Duration::ZERO);
        for _ in 0..3 {
            sleep_for(&clock, Duration::from_millis(400));
        }
        assert!(watch.woke(), "1.2 s asleep in all");
    }

    #[test]
    fn without_the_clocks_nothing_is_a_wake() {
        let watch = Watch::new(Box::new(|| None));
        assert!(!watch.woke());
    }

    /// The behaviour on this platform (run on Windows, Linux and macOS):
    /// its clocks can be read, and while the machine is awake they never
    /// report a sleep.
    #[test]
    fn this_platforms_clocks_read_and_stand_still_while_awake() {
        let first = slept().expect("the sleep clocks are readable on this platform");
        let watch = Watch::system();
        for _ in 0..10_000 {
            assert!(!watch.woke(), "no wake while the machine is awake");
        }
        let last = slept().expect("still readable");
        assert!(last.abs_diff(first) < THRESHOLD, "{first:?} then {last:?}");
    }
}

// D2 (SC-018): give the macOS runner's display room for the reference's
// 1440 x 900 window. Lists every mode the display offers, then switches, for
// the login session, to the smallest one that holds a 1440 x 900 page with
// the title bar and the menu bar. Prints what it found and what it set; exits
// 3 when no such mode exists (the visual scenario then records the size as
// capability-unavailable).

import CoreGraphics
import Foundation

let display = CGMainDisplayID()
let options = [kCGDisplayShowDuplicateLowResolutionModes: kCFBooleanTrue] as CFDictionary
let modes = (CGDisplayCopyAllDisplayModes(display, options) as? [CGDisplayMode]) ?? []
let current = CGDisplayBounds(display)
print("display \(display): \(Int(current.width))x\(Int(current.height)), \(modes.count) modes")
for mode in modes {
  print("  mode \(mode.width)x\(mode.height) (pixels \(mode.pixelWidth)x\(mode.pixelHeight)) usable=\(mode.isUsableForDesktopGUI())")
}
let fitting = modes
  .filter { $0.width >= 1440 && $0.height >= 1000 && $0.isUsableForDesktopGUI() }
  .sorted { $0.width * $0.height < $1.width * $1.height }
guard let target = fitting.first else {
  print("no mode of at least 1440x1000 is offered")
  exit(3)
}
var config: CGDisplayConfigRef?
guard CGBeginDisplayConfiguration(&config) == .success else { print("cannot begin a configuration"); exit(3) }
CGConfigureDisplayWithDisplayMode(config, display, target, nil)
let result = CGCompleteDisplayConfiguration(config, .forSession)
let after = CGDisplayBounds(display)
print("set \(target.width)x\(target.height): \(result.rawValue); display now \(Int(after.width))x\(Int(after.height))")
exit(result == .success && after.width >= 1440 && after.height >= 1000 ? 0 : 3)

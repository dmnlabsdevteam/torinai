import LocalAuthentication
import SwiftUI

/// Touch ID gate on the app itself.
///
/// This is a LOGIN gate: it decides whether the window opens. It is not a
/// secrecy boundary, and it is worth being clear about that rather than letting
/// the padlock imply more than it does -- the logs and the database this reads
/// are protected by file permissions and Postgres auth, exactly as they were
/// before. What the gate buys is that a dashboard showing what the substrate is
/// doing does not sit open on an unattended screen.
@MainActor
final class Gate: ObservableObject {
    enum State: Equatable {
        case locked
        case authenticating
        case unlocked
        case failed(String)
    }

    @Published private(set) var state: State = .locked

    /// Biometry, with device passcode as the fallback -- a Mac whose sensor is
    /// wet or whose user is wearing gloves must still be able to get in.
    private let policy: LAPolicy = .deviceOwnerAuthentication

    func authenticate() {
        let context = LAContext()
        context.localizedCancelTitle = "Quit"

        var error: NSError?
        guard context.canEvaluatePolicy(policy, error: &error) else {
            // SAY WHY. "Authentication unavailable" with no cause sends you
            // hunting through system settings for a reason the OS already gave.
            state = .failed(error?.localizedDescription
                            ?? "Touch ID and passcode are both unavailable")
            return
        }

        state = .authenticating
        context.evaluatePolicy(policy,
                               localizedReason: "unlock the TorinAI dashboard") {
            ok, evalError in
            Task { @MainActor in
                if ok {
                    self.state = .unlocked
                } else if let laError = evalError as? LAError,
                          laError.code == .userCancel || laError.code == .appCancel {
                    self.state = .locked          // cancelling is not a failure
                } else {
                    self.state = .failed(evalError?.localizedDescription
                                         ?? "Authentication failed")
                }
            }
        }
    }

    func lock() { state = .locked }
}

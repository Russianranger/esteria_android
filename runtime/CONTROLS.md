# Initial controller and keyboard implementation

`GameInputRouter` and `GameInputView` are implemented against the real XTest
transport and Surface bridge, connected through the Service-owned presentation
panel. Host behavior checks pass. Actual Android/controller and game UI behavior
are not qualified by those checks.
The mapping assumes the client's standard keyboard bindings and a US X11 keymap.
Existing custom keybindings can differ and must be surfaced in setup, not overwritten.

| Control | Camera mode | Pointer mode (Y toggle) |
| --- | --- | --- |
| Left stick | W/S forward/back, Q/E strafe | Arrow-key menu navigation |
| Right stick | Relative camera with right mouse held | Relative mouse pointer |
| A | Space / jump | Left click |
| B | Action bar 1 | Escape |
| X | B / bags | B / bags |
| Y | Switch to pointer mode | Switch to camera mode |
| Left shoulder | Tab / target | Tab / focus |
| Right shoulder | Action bar 2 | Enter |
| D-pad / hat | Action bar 3/4/5/6 (up/right/down/left) | Arrow keys |
| Left / right trigger | Left / right mouse | Left / right mouse |
| Start / Select | Escape / map | Escape / map |
| Left / right stick press | Quest log / character pane | Quest log / character pane |
| Primary touch | Absolute pointer with left-button drag/click | Same |

Right trigger at the pointed NPC/object provides the initial interaction route;
there is no unverified assumption that F is an interact binding. Basic inventory,
quest and loot actions use the pointer/touch route. Actual game behavior still
requires matching assets and a running client.

Stick deadzones use hysteresis; camera deltas integrate frame time and cap a late
frame to 50 ms. Touch and controller buttons retain independent ownership. Y
neutralizes old held input before changing mode. Focus loss, controller removal,
Surface destruction, pause and shutdown release keys/buttons. A broken/full
transport reports failure; it does not silently drop a key-up. Controls do not
inject input until supplied with a connected session sink.

The session owner pairs `pauseInput()` with `resumeInput()`. Input is also gated
until a frame has arrived on a valid attached Surface and the window has focus.
Switching controller devices neutralizes the previous device. Keyboard hide,
focus loss, pause and Surface destruction invalidate old IME connections, so
late callbacks cannot type into a resumed game. Composition backspace and Enter
operate on the staged draft before any guest text is emitted; unsupported dead
keys are rejected without crashing the input callback.

The presentation toolbar exposes `showKeyboard()` / `hideKeyboard()`. The initial
IME adapter supports printable ASCII, Tab, Enter and
backspace. It stages composition, validates complete commits, emits explicit Shift
plus base keys, and atomically reserves at most 256 input events (64 characters)
before queueing a commit. Unsupported Unicode or larger pastes are rejected without
partial text. Text is not logged or included in support receipts. Unicode layout
support and actual keyboard/game field tests remain open.

Software-keyboard Done, generic Enter actions and Enter key events submit the
pending composition followed by Enter in one accepted sequence. The keyboard
hides only after acceptance; closing that connection and invalidating its
generation prevents a later action/key callback from submitting twice. Back,
pause and focus loss discard the draft and reject stale callbacks. Unsupported
editor actions preserve the draft and return false. A whole-batch capacity refusal
happens before any event is accepted, retains the draft and leaves the keyboard
available to retry. Transport I/O errors and ambiguous individual-key overload
still fail the session. Ordinary 64-character text plus Enter is accepted, while a heavily
shifted draft needing more than the unchanged 256-event transport limit is
rejected explicitly before any event is queued; shorten it or commit it first.
These guards have host sequence/lifecycle evidence, not actual Android IME or
in-game field qualification.

Every new Android input connection receives a distinct generation, and closing
it invalidates its own composition before Android's base close callback runs.
An older connection cannot type into its replacement during the same shown
keyboard session. Actual replacement/close callbacks remain Android validation
gates; the source wiring is compiled and reviewed.

Run `./gradlew :core:gameInputTest`. These checks establish mapping/state behavior,
not physical Thor controller layout, Wine focus, game combat/quest functionality,
or combined-runtime latency.


The presentation panel now reserves space for its Keyboard/Stop controls and
fits the game Surface to the remaining viewport with its source aspect ratio.
The toolbar no longer covers the bottom hotbar, and touch coordinates are local
to the fitted game view. Application Java/lint pass; complete guest gameplay,
controller usability and hardware presentation remain separate qualifications.

`android-presentation.yml` now also prepares a real Android13 x64 widget/IME
component case: visible software keyboard, composition plus Done/Enter, bounded
whole-batch retry, stale/closed connections, touch and constructed controller
KeyEvents. A test-only uinput registration can additionally supply real framework
joystick ranges for constructed MotionEvents; unavailable registration leaves
stick/camera qualification false. No Android execution result is claimed until
that exact workflow runs. The fixed recording sink does not exercise Wine/X11,
physical controller delivery or game fields. See `ANDROID-INPUT-QUALIFICATION.md`.

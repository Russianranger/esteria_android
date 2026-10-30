# Initial controller and keyboard implementation

`GameInputRouter` and `GameInputView` are implemented against the real XTest
transport and Surface bridge. They are internal components awaiting owned runtime
session wiring; the launcher does not yet activate a game view. Host behavior
checks pass. Actual Android/controller and game UI behavior are not qualified.
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

The view exposes `showKeyboard()` / `hideKeyboard()` for the future accessible
in-game toolbar. The initial IME adapter supports printable ASCII, Tab, Enter and
backspace. It stages composition, validates complete commits, emits explicit Shift
plus base keys, and atomically reserves at most 256 input events (64 characters)
before queueing a commit. Unsupported Unicode or larger pastes are rejected without
partial text. Text is not logged or included in support receipts. Unicode layout
support and actual keyboard/game field tests remain open.

Run `./gradlew :core:gameInputTest`. These checks establish mapping/state behavior,
not physical Thor controller layout, Wine focus, game combat/quest functionality,
or combined-runtime latency.


The presentation panel now reserves space for its Keyboard/Stop controls and
fits the game Surface to the remaining viewport with its source aspect ratio.
The toolbar no longer covers the bottom hotbar, and touch coordinates are local
to the fitted game view. Application Java/lint pass; complete guest gameplay,
controller usability and hardware presentation remain separate qualifications.

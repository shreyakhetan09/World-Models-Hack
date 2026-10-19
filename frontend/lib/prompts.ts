// Layered prompt composition for LingBot World 2, following Reactor's prompt guide:
//   prompt = base + camera[moving] + movement[moving] + events
// The base (scenario.world_prompt) says WHAT the world is; these layers say how the camera behaves
// and what the robot is doing. Recompose whenever the moving state flips so text matches motion.
// Keep the template sentences verbatim: paraphrases read as different instructions to the model.

const ANCHOR = "the robot's dark front chassis and twin treads";

export const CAMERA = {
  static:
    `Strict first-person view from a rescue robot, ${ANCHOR} holding steady at the bottom centre of the frame. ` +
    "Neither the robot nor the camera moves on its own; arrow-key look-input is the only source of camera motion, " +
    "turning the view only while held.",
  dynamic:
    `Strict first-person view, ${ANCHOR} holding steady at the bottom centre of the frame as the viewpoint ` +
    "advances through the scene; look-input becomes the heading changing.",
};

export const MOVEMENT = {
  static:
    "The robot waits in place, its treads settled on the floor, dust drifting slowly through the beam of its " +
    "headlight and a faint red status light blinking on the chassis.",
  dynamic:
    "The robot rolls steadily forward on its treads, grinding over small debris, the floor ahead sliding " +
    "toward the camera as the surroundings pass by on both sides.",
};

export function composePrompt(base: string, moving: boolean, events: string[] = []): string {
  const parts = [base, moving ? CAMERA.dynamic : CAMERA.static, moving ? MOVEMENT.dynamic : MOVEMENT.static, ...events];
  return parts.join(" ").slice(0, 2000);
}

#include "raylib.h"
#include "raymath.h"

#include <math.h>
#include <stdio.h>

static float clampf(float v, float lo, float hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static void fit_camera(Model model, Vector3 *target, float *distance)
{
    BoundingBox box = GetModelBoundingBox(model);
    Vector3 size = Vector3Subtract(box.max, box.min);

    *target = Vector3Scale(Vector3Add(box.min, box.max), 0.5f);

    float radius = fmaxf(size.x, fmaxf(size.y, size.z)) * 0.5f;
    if (radius < 0.001f) radius = 1.0f;

    *distance = radius * 3.0f;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s model.obj\n", argv[0]);
        return 1;
    }

    const char *path = argv[1];

    SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT);
    InitWindow(1280, 800, "Halo Arena - Model Viewer");
    SetTargetFPS(144);

    Model model = LoadModel(path);
    if (!IsModelValid(model)) {
        fprintf(stderr, "failed to load model: %s\n", path);
        CloseWindow();
        return 1;
    }

    Vector3 target = {0};
    float distance = 5.0f;
    fit_camera(model, &target, &distance);

    float yaw = DEG2RAD * 45.0f;
    float pitch = DEG2RAD * 20.0f;
    bool wireframe = false;

    Camera3D camera = {0};
    camera.target = target;
    camera.up = (Vector3){0, 0, 1};
    camera.fovy = 45.0f;
    camera.projection = CAMERA_PERSPECTIVE;

    while (!WindowShouldClose()) {
        Vector2 mouse = GetMouseDelta();

        if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
            yaw -= mouse.x * 0.008f;
            pitch += mouse.y * 0.008f;
            pitch = clampf(pitch, DEG2RAD * -89.0f, DEG2RAD * 89.0f);
        }

        float wheel = GetMouseWheelMove();
        if (wheel != 0.0f) {
            distance *= powf(0.85f, wheel);
            distance = clampf(distance, 0.001f, 1000000.0f);
        }

        if (IsKeyPressed(KEY_R) || IsKeyPressed(KEY_F)) {
            fit_camera(model, &target, &distance);
            yaw = DEG2RAD * 45.0f;
            pitch = DEG2RAD * 20.0f;
        }

        if (IsKeyPressed(KEY_W)) wireframe = !wireframe;

        // Shift + middle mouse pans the orbit target.
        if (IsMouseButtonDown(MOUSE_BUTTON_MIDDLE)) {
            Vector3 forward = Vector3Normalize(Vector3Subtract(camera.target, camera.position));
            Vector3 right = Vector3Normalize(Vector3CrossProduct(forward, camera.up));
            Vector3 up = Vector3Normalize(Vector3CrossProduct(right, forward));

            float scale = distance * 0.0015f;
            target = Vector3Add(target, Vector3Scale(right, -mouse.x * scale));
            target = Vector3Add(target, Vector3Scale(up, mouse.y * scale));
        }

        float cp = cosf(pitch);
        camera.target = target;
        camera.position = (Vector3){
            target.x + distance * cp * cosf(yaw),
            target.y + distance * cp * sinf(yaw),
            target.z + distance * sinf(pitch)
        };

        BeginDrawing();
        ClearBackground((Color){28, 30, 34, 255});

        BeginMode3D(camera);

        if (wireframe) DrawModelWires(model, (Vector3){0, 0, 0}, 1.0f, RAYWHITE);
        else DrawModel(model, (Vector3){0, 0, 0}, 1.0f, LIGHTGRAY);

        DrawLine3D((Vector3){0,0,0}, (Vector3){1,0,0}, RED);
        DrawLine3D((Vector3){0,0,0}, (Vector3){0,1,0}, GREEN);
        DrawLine3D((Vector3){0,0,0}, (Vector3){0,0,1}, BLUE);

        EndMode3D();

        DrawRectangle(8, 8, 470, 92, Fade(BLACK, 0.65f));
        DrawText(path, 18, 16, 18, RAYWHITE);
        DrawText("LMB drag: orbit   Wheel: zoom   MMB drag: pan", 18, 44, 18, RAYWHITE);
        DrawText("R/F: frame model   W: wireframe   Esc: quit", 18, 70, 18, RAYWHITE);

        EndDrawing();
    }

    UnloadModel(model);
    CloseWindow();
    return 0;
}

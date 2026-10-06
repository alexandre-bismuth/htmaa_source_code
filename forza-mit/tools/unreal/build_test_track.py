"""Build /Game/Cambridge/Maps/DriveTest: an 8 km x 400 m flat slab (exact box collision) for
automated acceleration / top-speed tests with -DriveTest. Run via build_test_track.sh."""
import unreal

MAP = "/Game/Cambridge/Maps/DriveTest"
GAME_MODE = "/Script/CambridgeRacer.CambridgeGameMode"
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

assert level_editor.new_level_from_template(MAP, "/Engine/Maps/Templates/Template_Default")
for a in actors.get_all_level_actors():
    if isinstance(a, (unreal.StaticMeshActor, unreal.PlayerStart)):
        actors.destroy_actor(a)

# engine cube is 100 cm, centred; top face at z = 0, track runs from x = -100 m to +7.9 km
slab = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(390000.0, 0.0, -50.0))
slab.set_actor_label("TestTrack")
smc = slab.get_editor_property("static_mesh_component")
smc.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
slab.set_actor_scale3d(unreal.Vector(8000.0, 400.0, 1.0))  # 8 km x 400 m (room for the skidpad circle)

ps = actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0.0, 0.0, 150.0), unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
ps.set_actor_label("PlayerStart_Test")
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
world.get_world_settings().set_editor_property("default_game_mode", unreal.load_class(None, GAME_MODE))
assert level_editor.save_current_level()

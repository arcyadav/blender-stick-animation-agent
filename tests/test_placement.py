"""Placement helpers put objects exactly on / next to others.  python -m tests.test_placement"""
import config
from blender_worker.client import BlenderWorker, ToolError


def close(a, b, tol=0.01):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def main():
    with BlenderWorker(config.OUTPUTS / "test_placement") as w:
        w.call("scene_reset")
        w.call("add_primitive", type="cube", name="block", location=[1, 2, 0], size=0.8)
        top = w.call("add_primitive", type="sphere", name="ball", location={"on_top_of": "block"}, size=0.3)
        flat = w.call("add_primitive", type="cube", name="flat", location=[-2, 0.5], size=0.2)
        assert close(flat["bottom_centre"], [-2, 0, 0.5]), flat
        assert close(top["bottom_centre"], [1, 2, 0.8]), top

        side = w.call("add_primitive", type="cylinder", name="can", location={"next_to": "block", "side": "left"},
                      size=0.4)
        # block spans x 0.6..1.4; can half-width 0.2, gap 0.2 → centre x = 0.6 - 0.2 - 0.2
        assert close(side["bottom_centre"], [0.2, 2, 0]), side

        front = w.call("add_primitive", type="cone", name="cone", location=[3, 0], size=0.5, layer="front")
        assert close(front["bottom_centre"], [3, -1, 0]) and front["layer"] == "front", front

        # keyframed location via a placement, and rotation keeps the bottom on the ground
        w.call("keyframe", name="ball", property="location", frame=30, value={"on_top_of": "can"})
        moved = w.call("set_transform", name="block", rotation=45)
        assert abs(moved["bottom_centre"][2]) < 0.01, moved

        try:
            w.call("add_primitive", type="cube", name="block")
            raise AssertionError("duplicate name accepted")
        except ToolError as e:
            assert "already exists" in str(e)
        state = w.call("scene_state")
        assert [o["name"] for o in state["objects"]] == ["ground", "block", "ball", "flat", "can", "cone"], state
        print("all placement tests passed")


if __name__ == "__main__":
    main()

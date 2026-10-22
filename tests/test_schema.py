"""Validation catches the mistakes seen on Day 0 with clear messages.  python -m tests.test_schema"""
from blender_worker.schema import ValidationError, validate


def rejects(tool, args, *must_contain):
    try:
        validate(tool, args)
    except ValidationError as e:
        for s in must_contain:
            assert s in str(e), f"{s!r} not in {e}"
        return str(e)
    raise AssertionError(f"accepted {tool} {args}")


def main():
    # qwen2.5:7b on Day 0: colour put inside location
    msg = rejects("add_primitive", {"type": "sphere", "name": "red_ball",
                                    "location": {"colour": "red", "on_top_of": "table"}},
                  "add_primitive.location", "'colour' is a separate argument")
    print("ok:", msg)

    clean, warn = validate("add_primitive", {"type": "sphere", "name": "b", "location": {"on_top_of": "table"},
                                             "colour": "red"})
    assert clean["location"] == {"on_top_of": "table"} and not warn

    clean, warn = validate("add_primitive", {"type": "cube", "name": "c", "location": ["1", 0, 0]})
    assert clean["location"] == [1.0, 0, 0] and warn

    rejects("add_primitive", {"type": "pyramid", "name": "p"}, "must be one of")
    rejects("add_primitive", {"name": "p"}, "missing required argument 'type'")
    rejects("add_primitive", {"type": "cube", "name": "p", "location": [0]}, "height of the object")
    clean, _ = validate("add_primitive", {"type": "cube", "name": "p", "location": [1.5, 0]})
    assert clean["location"] == [1.5, 0]
    validate("play_action", {"name": "man", "action": "walk", "to": "table"})
    rejects("play_action", {"name": "man", "action": "dance"}, "must be one of")
    rejects("camera_move", {"kind": "orbit"}, "must be one of")
    validate("keyframe", {"name": "b", "property": "rotation", "frame": 1, "value": 90})
    rejects("add_primitive", {"type": "cube", "name": "p", "location": {"on_top_of": "t", "next_to": "u"}},
            "exactly one")
    rejects("teleport", {}, "unknown tool")
    rejects("keyframe", {"name": "b", "property": "rotation", "frame": 1, "value": {"on_top_of": "t"}},
            "keyframe.value")
    validate("keyframe", {"name": "b", "property": "location", "frame": 10, "value": {"on_top_of": "table"}})
    validate("keyframe", {"name": "b", "property": "colour", "frame": 10, "value": "blue"})
    rejects("keyframe", {"name": "b", "property": "location", "frame": 2.5, "value": [0, 0, 0]}, "whole number")
    print("all schema tests passed")


if __name__ == "__main__":
    main()

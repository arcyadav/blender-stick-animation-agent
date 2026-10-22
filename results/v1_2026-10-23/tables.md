| agent | tasks | pass (after fixes) | pass first try | tool calls / task | invalid calls | tool errors | s / task |
|---|---|---|---|---|---|---|---|
| A1 | 30 | 2 (7%) | 2 | 42.8 | 20% | 44% | 47 |
| A2 | 30 | 8 (27%) | 8 | 15.2 | 2% | 13% | 45 |
| A3 | 30 | 30 (100%) | 27 | 5.9 | 0% | 1% | 23 |

| category | A1 | A2 | A3 |
|---|---|---|---|
| static_layout | 0/3 | 1/3 | 3/3 |
| object_motion | 0/5 | 0/5 | 5/5 |
| figure_single | 2/6 | 4/6 | 6/6 |
| figure_sequence | 0/6 | 2/6 | 6/6 |
| figure_props | 0/6 | 1/6 | 6/6 |
| two_figures_camera | 0/4 | 0/4 | 4/4 |

Most common failing checks:
- A1: actions_in_order ×19, on_surface ×11, moves ×8, reaches ×5, camera_move ×4, faces ×3
- A2: on_surface ×12, actions_in_order ×11, in_view ×5, clip_length_s ×4, no_hover ×4, moves ×4
- A3: none

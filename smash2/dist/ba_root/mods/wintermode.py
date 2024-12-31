# Released under the MIT License. See LICENSE for details.
#
"""
This plugin introduces a snowfall effect in the game, adding a dynamic weather element to the gameplay experience.

Features:
- Generates random snowflakes that fall from the sky, enhancing the winter atmosphere.
- Customizes the snow's appearance based on the current game map, adjusting the snowdrift's color and texture.
- Allows players to leave footprints in the snow, adding realism to movement.
- Includes functionality for toggling a hockey mode, altering surface friction and material properties for a unique gameplay experience.

Usage:
Simply install the plugin, and it will automatically initiate the snowfall when a game starts.
The plugin will also adjust the environment based on specific map conditions, providing an immersive experience for players.

Compatibility:
Designed for the game API version 8. Ensure your game version is compatible for optimal performance.
if you are running on API9, just change the number in the meta-tag from 8 to 9.
Like this:
# ba meta require api 9

Note:
Feel free to customize or extend this plugin to suit your gameplay needs!

Discord:
- vladdos5556
"""
#
# Tell the app which of its api versions we are written for. The app's
# meta-scanner will skip this file if this number doesn't match theirs.
# To learn more, see https://ballistica.net/wiki/meta-tag-system
# ba_meta require api 8

from __future__ import annotations

__author__ = 'vladdos'
__version__ = '1.0'

import random
import math
from typing import Any, Sequence

import babase
import bascenev1
from bascenev1lib.gameutils import SharedObjects
from bascenev1lib.actor.spaz import Spaz
from bascenev1lib.actor.spazfactory import SpazFactory


class FootingMessage:
    """Indicates a change in player footing (on ground or off ground)."""
    def __init__(self, value: int = 1) -> None:
        self.value: int = value


original__init__ = Spaz.__init__


def new__init__(
    self: Spaz,
    *,
    color: Sequence[float] = (1.0, 1.0, 1.0),
    highlight: Sequence[float] = (0.5, 0.5, 0.5),
    character: str = 'Spaz',
    source_player: bascenev1.Player | None = None,
    start_invincible: bool = True,
    can_accept_powerups: bool = True,
    powerups_expire: bool = False,
    demo_mode: bool = False,
    **kwargs: Any,
) -> None:
    original__init__(
        self,
        color=color,
        highlight=highlight,
        character=character,
        source_player=source_player,
        start_invincible=start_invincible,
        can_accept_powerups=can_accept_powerups,
        powerups_expire=powerups_expire,
        demo_mode=demo_mode,
        **kwargs,
    )
    self.footing = False


original_handlemessage = Spaz.handlemessage


def new_handlemessage(self: Spaz, msg: Any) -> Any:
    if isinstance(msg, FootingMessage):
        self.footing = (msg.value == 1)

    return original_handlemessage(self, msg)


original_factory__init__ = SpazFactory.__init__


def new_factory__init__(self: SpazFactory) -> None:
    original_factory__init__(self)
    shared = SharedObjects.get()
    footing_material = shared.footing_material

    self.roller_material.add_actions(
        conditions=('they_have_material', footing_material),
        actions=(
            ('message', 'our_node', 'at_connect', FootingMessage(1)),
            ('message', 'our_node', 'at_disconnect', FootingMessage(-1)),
        ),
    )


class Snowflake(bascenev1.Actor):
    def __init__(snowflake: Snowflake,
                 position: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 scale: float = 1.0,
                 respawn: bool = False):
        super().__init__()
        snowflake.owner = None
        snowflake.position = position
        snowflake.scale = scale
        snowflake.respawn = respawn

        activity = bascenev1.getactivity()

        material = bascenev1.Material()
        material.add_actions(('modify_part_collision', 'collide', False))

        void_material = [material]

        if activity.globalsnode.slow_motion:
            velocity = (0.0, -3.5 * random.uniform(0.8, 1.2), 0.0)
        else:
            velocity = (0.0, -1.75 * random.uniform(0.8, 1.2), 0.0)

        snowflake.node: bascenev1.Node = bascenev1.newnode(
            'prop',
            delegate=snowflake,
            attrs={
                'is_area_of_interest': False,
                'reflection_scale': [0.1, 0.1, 0.3],
                'reflection': 'soft',
                'color_texture': bascenev1.gettexture('white'),
                'mesh': bascenev1.getmesh('frostyPelvis'),
                'shadow_size': 0.0,
                'mesh_scale': 0.15 * snowflake.scale * 0.5,
                'materials': void_material,
                'velocity': velocity,
                'position': position,
                'body_scale': 0.03 * scale * 0.5,
                'body': 'sphere',
                'gravity_scale': 0.0,
            },
        )
        snowflake.fall_timer = bascenev1.Timer(
            time=0.01,
            call=snowflake.check_height,
            repeat=True,
        )

    def check_height(snowflake: Snowflake) -> None:
        try:
            if snowflake.node.position[1] > 1.0:
                return
        except:
            pass
        snowflake.fall_timer = None
        snowflake.handlemessage(bascenev1.OutOfBoundsMessage())

    def handlemessage(snowflake: Snowflake, msg: Any) -> Any:
        if isinstance(msg, bascenev1.DieMessage):
            snowflake.node.delete()

        elif isinstance(msg, bascenev1.OutOfBoundsMessage):
            activity = snowflake.getactivity()
            if snowflake.respawn:
                if hasattr(activity, 'snowfall') and not activity.snowfall:
                    snowflake.node.position = snowflake.position
                    snowflake.fall_timer = bascenev1.Timer(
                        time=0.01,
                        call=snowflake.check_height,
                        repeat=True,
                    )
            else:
                snowflake.handlemessage(bascenev1.DieMessage())
        else:
            super().handlemessage(msg)
 

class Node(bascenev1.Actor):
    def __init__(
        node: Node, 
        position: tuple[float, float, float], 
        mesh: bascenev1.Mesh, 
        texture: bascenev1.Texture, 
        scale: float = 1.0,
    ):
        super().__init__()
        
        node.position = position
        node.mesh = mesh
        node.texture = texture
        node.scale = scale

        node._initialize_materials()
        node.main_node = node._create_main_node()

        node.collision_region_lower = node._create_collision_region(
            offset_y=-0.6, offset_z=-0.54,
        )
        node.collision_region_upper = node._create_collision_region(
            offset_y=1.0, offset_z=0.54,
        )

        node._start_movement_animation()

    def _initialize_materials(node: Node) -> Node:
        node.collision_material = bascenev1.Material()
        node.non_collision_material = bascenev1.Material()

        node.collision_material.add_actions(
            conditions=('they_are_different_node_than_us', ),
            actions=(('modify_part_collision', 'collide', False),)
        )
        node.collision_material.add_actions(
            conditions=('they_have_material', node.non_collision_material),
            actions=(('modify_part_collision', 'collide', True),)
        )

        node.non_collision_material.add_actions(
            conditions=('they_are_different_node_than_us', ),
            actions=(('modify_part_collision', 'collide', False),)
        )
        node.non_collision_material.add_actions(
            conditions=('they_have_material', node.collision_material),
            actions=(('modify_part_collision', 'collide', True),)
        )

    def _create_main_node(node: Node) -> bascenev1.Node:
        main_node: bascenev1.Node = bascenev1.newnode(
            'prop',
            attrs={
                'color_texture': node.texture,
                'mesh': node.mesh,
                'shadow_size': 0.0,
                'mesh_scale': node.scale,
                'materials': [node.non_collision_material],
                'position': node.position,
                'body': 'puck',
                'gravity_scale': 1.0,
            },
        )
        return main_node

    def _create_collision_region(
        node: Node,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        offset_z: float = 0.0,
    ) -> bascenev1.Node:
        collision_node: bascenev1.Node = bascenev1.newnode(
            'region',
            attrs={
                'position': (
                    node.position[0] + offset_x,
                    node.position[1] + offset_y,
                    node.position[2] + offset_z,
                ),
                'scale': (3.0, 0.5, 0.5),
                'materials': [node.collision_material],
                'type': 'box',
            },
        )
        return collision_node

    def _start_movement_animation(node: Node) -> None:
        def stop_movement() -> None:
            node.main_node.extra_acceleration = (0.0, 0.0, 0.0)
            node.main_node.velocity = (0.0, 0.0, 0.0)
            node.main_node.gravity_scale = 0.0

        def animate_movement() -> None:
            bascenev1.animate_array(
                node=node.collision_region_lower,
                attr='scale',
                size=3,
                keys={
                    0.0: (3.0, 0.5, 0.5),
                    0.03: (3.0, 4.0, 0.5),
                },
            )
            bascenev1.animate_array(
                node=node.collision_region_upper,
                attr='scale',
                size=3,
                keys={
                    0.0: (3.0, 0.5, 0.5),
                    0.03: (3.0, 4.0, 0.5),
                },
            )
            bascenev1.timer(time=0.035, call=stop_movement)

        bascenev1.timer(time=0.001, call=animate_movement)


class Footprint(bascenev1.Actor):
    def __init__(emit: Footprint,
                 source_player: bascenev1.Player | None = None,
                 scale: float = 1.0,
                 interval: float = 0.5):
        super().__init__()
        emit.owner = source_player.node
        emit.scale = max(0.1, min(10.0, scale))
        emit.interval = max(0.05, interval)
        emit.source_player = source_player

        offset = (0.0, 0.0, 0.0)

        try:
            activity = bascenev1.getactivity()
            if activity.globalsnode.slow_motion:
                emit.interval /= 3.0
        except:
            pass

        if emit.owner:
            emit.node: bascenev1.Node = bascenev1.newnode(
                'math',
                owner=emit.owner,
                attrs={
                    'input1': (offset[0], offset[1], offset[2]),
                    'operation': 'add',
                },
            )
            emit.owner.connectattr('position_center', emit.node, 'input2')

        emit.spawn_timer = bascenev1.Timer(
            time=emit.interval,
            call=emit._spawn,
            repeat=True,
        )

    def _spawn(emit: Footprint) -> None:
        if emit.owner:
            if not emit.source_player.footing:
                return
            move_length = math.hypot(
                emit.owner.move_up_down,
                emit.owner.move_left_right,
            )
            if move_length < 0.1:
               return
        else:
            return

        try:
            emit.footprint_node: bascenev1.Node = bascenev1.newnode(
                'scorch',
                attrs={
                    'position': emit.node.output,
                    'size': emit.scale * 0.3,
                    'big': False,
                    'color': (0.0, 0.0, 0.0),
                },
            )
            bascenev1.animate(
                node=emit.footprint_node,
                attr='presence',
                keys={
                    0.0: 1.0,
                    10.0: 0.0,
                },
            )
            emit.footprint_delete_timer = bascenev1.timer(
                time=10.0,
                call=emit.footprint_node.delete,
            )
        except:
            emit.handlemessage(bascenev1.DieMessage())

    def handlemessage(emit: Footprint, msg: Any) -> Any:
        if isinstance(msg, bascenev1.DieMessage):
            emit.spawn_timer = None
            if emit and emit.node:
                emit.node.delete()


original_on_begin = bascenev1.GameActivity.on_begin


def on_begin(activity: bascenev1.GameActivity) -> None:
    original_on_begin(activity)
    activity._start_snow()
    activity.spawn_snowdrift_start()


def _start_snow(activity: bascenev1.GameActivity) -> None:
    boxes = activity.map.defs.boxes
    map_size = boxes['map_bounds'][6] * boxes['map_bounds'][8]

    activity.snowing = True
    activity.snowfall = True

    activity.stop_spawn_timer = bascenev1.Timer(
        time=4.0,
        call=activity.stop_spawn,
    )
    activity.snow_timer = bascenev1.Timer(
        time=30.0 / map_size * random.uniform(1.0, 1.0) / 3.0,
        call=activity._snow,
        repeat=True,
    )


def _stop_snow(activity: bascenev1.GameActivity) -> None:
    activity.snow_timer = None
    activity.snowing = False
    activity.snowfall = True
    activity.stop_spawn_timer = None


def _snow(activity: bascenev1.GameActivity) -> None:
    if not activity.snowfall:
        return

    boxes = activity.map.defs.boxes
    position = (
        random.uniform(
            boxes['map_bounds'][0] - 0.5 * boxes['map_bounds'][6],
            boxes['map_bounds'][0] + 0.5 * boxes['map_bounds'][6],
        ),
        boxes['map_bounds'][1] + 0.4 * boxes['map_bounds'][7],
        random.uniform(
            boxes['map_bounds'][2] - 0.5 * boxes['map_bounds'][8],
            boxes['map_bounds'][2] + 0.5 * boxes['map_bounds'][8],
        ),
    )

    snowflake = Snowflake(position=position, respawn=True).autoretain()

    snowflake.node.reflection_scale = [0.75, 0.75, 1.1]
    snowflake.node.mesh_scale *= random.uniform(0.05, 2.5)


def stop_spawn(activity: bascenev1.GameActivity) -> None:
    if activity.snowing:
        activity.snowfall = False


def spawn_snowdrift_start(activity: bascenev1.GameActivity) -> None:
    if not hasattr(activity, 'current_tint'):
        activity.current_tint = activity.globalsnode.tint
    current_tint = activity.globalsnode.tint
    new_tint = (
        0.9 * current_tint[0], 
        0.9 * current_tint[1],
        1.1 * current_tint[2],
    )

    bascenev1.animate_array(
        node=activity.globalsnode,
        attr='tint',
        size=3,
        keys={
            0.0: current_tint,
            0.025: (0.0, 0.0, 0.0),
            0.15: (0.0, 0.0, 0.0),
            0.5: new_tint,
        },
    )

    bascenev1.timer(
        time=0.075,
        call=babase.Call(
            spawn_snowdrift, activity,
        ),
    )


def spawn_snowdrift(activity: bascenev1.GameActivity) -> None:
    snow_node = activity.map.floor if hasattr(activity.map, 'floor') else activity.map.node
    snow_node_color = (
        0.55 * snow_node.color[0],
        0.55 * snow_node.color[1],
        0.65 * snow_node.color[2],
    )

    position = None
    position_2 = None

    if activity.map.name in ['Happy Thoughts', 'Lake Frigid']:
        return

    if activity.map.name == 'Courtyard':
        position = (0.02, 0.15, 0.04)

    elif activity.map.name == 'Football Stadium':
        position = (0.02, 0.15, 0.03)

    elif activity.map.name == 'Hockey Stadium':
        position = (0.02, 0.16, 0.03)

        activity.map_node_2 = Node(
            position=position,
            mesh=activity.map.stands.mesh,
            texture=activity.map.stands.color_texture,
            scale=0.993,
        )
        activity.map.stands.opacity = 0.6
        activity.map.stands.color = snow_node_color
        activity.map.stands.color_texture = bascenev1.gettexture('white')

        activity.globalsnode.floor_reflection = False
        activity.hockey_on()

    elif activity.map.name in ['Big G', 'Bridgit', 'Crag Castle', 'Monkey Face', 'Doom Shroom', 'Roundabout', 'Zigzag']:
        if activity.map.name == 'Monkey Face':
            position = (0.02, 0.14, 0.0)
        elif activity.map.name == 'Big G':
            position = (0.0, 0.18, 0.01)
        else: 
            position = (0.02, 0.18, 0.03)

        if activity.map.name == 'Doom Shroom':
            position_2 = (0.0, 0.02, 0.35)
        else:
            position_2 = (0.0, 0.0, 0.05)

        if activity.map.name == 'Big G':
            activity.hockey_on()

        if activity.map.name != 'Crag Castle':
            activity.map_node_2 = Node(
                position=position_2,
                mesh=activity.map.background.mesh,
                texture=activity.map.background.color_texture,
                scale=0.993,
            )
            activity.map.background.opacity = 0.9
            activity.map.background.color = snow_node_color
            activity.map.background.color_texture = bascenev1.gettexture('white')

        if activity.map.name == 'Doom Shroom':
            activity.map_node_3 = Node(
                position=(0.02, -0.02, -0.2),
                mesh=activity.map.stem.mesh,
                texture=activity.map.stem.color_texture,
                scale=0.993,
            )
            activity.map.stem.opacity = 0.45
            activity.map.stem.color = snow_node_color
            activity.map.stem.color_texture = bascenev1.gettexture('white')

    elif activity.map.name == 'Rampage':
        position = (0.06, 0.15, 0.0)
        position_2 = (-0.05, 0.015, 0.1)

        activity.map_node_2 = Node(
            position=position_2,
            mesh=activity.map.background.mesh,
            texture=activity.map.background.color_texture,
            scale=0.993,
        )
        activity.map.background.opacity = 0.8
        activity.map.background.color = snow_node_color
        activity.map.background.color_texture = bascenev1.gettexture('white')

    elif activity.map.name == 'Step Right Up':
        position = (0.0225, 0.14, 0.03)

    elif activity.map.name == 'The Pad':
        position = (0.0, 0.1, 0.0)

    elif activity.map.name == 'Tip Top':
        position = (0.02, 0.17, 0.09)
        #activity.hockey_on()

    elif activity.map.name == 'Tower D':
        position = (0.0225, 0.15, 0.03)

    else:
        # custom maps
        position = (0.02, 0.16, 0.035)

    if activity.map.name in ['Courtyard', 'Crag Castle', 'Step Right Up', 'The Pad', 'Tower D']:
        activity.map.background.color = (0.92, 0.95, 1.1)

    elif activity.map.name == 'Rampage':
        activity.map.bg2.color = (0.95, 0.97, 1.1)

    scale = 1.0 if activity.map.name == 'Rampage' else 0.996 if activity.map.name in ['Step Right Up', 'Tower D'] else 0.993

    activity.map_node = Node(
        position=position,
        mesh=snow_node.mesh,
        texture=snow_node.color_texture,
        scale=scale,
    )
    snow_node.opacity = 0.75
    snow_node.color = snow_node_color
    snow_node.color_texture = bascenev1.gettexture('white')

    for player in activity.players:
        if player.actor and player.actor.is_alive():
            if not hasattr(player.actor, 'footprints') or not player.actor.footprints:
                player.actor.footprints = Footprint(
                    source_player=player.actor,
                    scale=0.25,
                    interval=0.25,
                )


def hockey_on(activity: bascenev1.GameActivity) -> None:
    shared = SharedObjects.get()
    if hasattr(activity, 'map'):
        if activity.map.is_hockey:
            activity.map.is_hockey = False
            activity.map.node.materials = [shared.footing_material]
            if hasattr(activity.map, 'floor'):
                activity.map.floor.materials = [shared.footing_material]
        else:
            activity.map.is_hockey = True
            if not hasattr(activity, 'ice_material'):
                material = bascenev1.Material()
                material.add_actions(
                    actions=('modify_part_collision', 'friction', 0.01),
                )
                activity.ice_material = material
            activity.map.node.materials = [
                shared.footing_material,
                activity.ice_material,
            ]
            if hasattr(activity.map, 'floor'):
                activity.map.floor.materials = [
                shared.footing_material,
                activity.ice_material,
            ]
        for player in activity.players:
            if player.actor and player.actor.is_alive():
                player.actor._hockey = activity.map.is_hockey
                player.actor.node.hockey = activity.map.is_hockey


Spaz.__init__ = new__init__
Spaz.handlemessage = new_handlemessage

SpazFactory.__init__ = new_factory__init__

bascenev1.GameActivity.on_begin = on_begin

bascenev1.GameActivity._start_snow = _start_snow
bascenev1.GameActivity._stop_snow = _stop_snow
bascenev1.GameActivity._snow = _snow
bascenev1.GameActivity.stop_spawn = stop_spawn

bascenev1.GameActivity.spawn_snowdrift_start = spawn_snowdrift_start
bascenev1.GameActivity.spawn_snowdrift = spawn_snowdrift

bascenev1.GameActivity.hockey_on = hockey_on


# Tell the app about our Plugin.
# ba_meta export plugin

class by_vladdos(babase.Plugin):
    def on_app_running(self) -> None:
        if not 'wintermode_version' in babase.app.config:
            babase.app.config['wintermode_version'] = __version__

        if not 'wintermode_author' in babase.app.config:
            babase.app.config['wintermode_author'] = __author__

        self.version = babase.app.config['wintermode_version']
        self.author = babase.app.config['wintermode_author']

        if not 'wintermode_launch_count' in babase.app.config:
            babase.app.config['wintermode_launch_count'] = 0

        launch_count = babase.app.config['wintermode_launch_count']
        
        if launch_count == 0:
            bascenev1.apptimer(
                time=0.75,
                call=self.show_welcome_message,
            )

        babase.app.config['wintermode_launch_count'] = launch_count + 1
        babase.app.config.commit()

    def show_welcome_message(self) -> None:
        babase.screenmessage(
            message=f'WinterMode Plugin v{self.version} by \ue063{self.author} has been successfully loaded.',
            color=(0.8, 0.9, 1.1),
        )
        def show_welcome_message_2() -> None:
            babase.screenmessage(
                message='Enjoy the winter-themed experience!',
                color=(0.0, 1.0, 0.0),
            )
        bascenev1.apptimer(
            time=1.25, # 2s after launching
            call=show_welcome_message_2,
        )

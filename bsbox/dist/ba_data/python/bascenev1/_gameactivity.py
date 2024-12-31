# Released under AGPL-3.0-or-later. See LICENSE for details.
#
# This file incorporates work covered by the following permission notice:
#   Released under the MIT License. See LICENSE for details.
#
"""Provides GameActivity class."""
# pylint: disable=too-many-lines

from __future__ import annotations

import time
import random
import logging
from typing import TYPE_CHECKING, TypeVar

from era import gdata
import babase
import _bascenev1

import bauiv1 as bui
from bascenev1._activity import Activity
from bascenev1._player import PlayerInfo
from bascenev1._messages import DieMessage, PlayerDiedMessage, StandMessage
from bascenev1._score import ScoreConfig
from bascenev1._gameutils import animate_array
from bascenev1 import _map
from bascenev1 import _music
from bascenev1lib.actor import themes
from bascenev1lib.actor import modifiers

if TYPE_CHECKING:
    from typing import Any, Callable, Sequence

    from bascenev1lib.actor.playerspaz import PlayerSpaz
    from bascenev1lib.actor.bomb import TNTSpawner
    import bascenev1

PlayerT = TypeVar('PlayerT', bound='bascenev1.Player')
TeamT = TypeVar('TeamT', bound='bascenev1.Team')


class GameActivity(Activity[PlayerT, TeamT]):
    """Common base class for all game bascenev1.Activities.

    Category: **Gameplay Classes**
    """

    # pylint: disable=too-many-public-methods

    # Tips to be presented to the user at the start of the game.
    tips: list[str | bascenev1.GameTip] = []

    # Default getname() will return this if not None.
    name: str | None = None

    # Default get_description() will return this if not None.
    description: str | None = None

    # Default get_available_settings() will return this if not None.
    available_settings: list[bascenev1.Setting] | None = None

    # Default getscoreconfig() will return this if not None.
    scoreconfig: bascenev1.ScoreConfig | None = None

    # Override some defaults.
    allow_pausing = True
    allow_kick_idle_players = True

    # Whether to show points for kills.
    show_kill_points = True

    # If not None, the music type that should play in on_transition_in()
    # (unless overridden by the map).
    default_music: bascenev1.MusicType | None = None

    @classmethod
    def create_settings_ui(
        cls,
        sessiontype: type[bascenev1.Session],
        settings: dict | None,
        completion_call: Callable[[dict | None], None],
    ) -> None:
        """Launch an in-game UI to configure settings for a game type.

        'sessiontype' should be the bascenev1.Session class the game will
          be used in.

        'settings' should be an existing settings dict (implies 'edit'
          ui mode) or None (implies 'add' ui mode).

        'completion_call' will be called with a filled-out settings dict on
          success or None on cancel.

        Generally subclasses don't need to override this; if they override
        bascenev1.GameActivity.get_available_settings() and
        bascenev1.GameActivity.get_supported_maps() they can just rely on
        the default implementation here which calls those methods.
        """
        assert babase.app.classic is not None
        delegate = babase.app.classic.delegate
        assert delegate is not None
        delegate.create_default_game_settings_ui(
            cls, sessiontype, settings, completion_call
        )

    @classmethod
    def getscoreconfig(cls) -> bascenev1.ScoreConfig:
        """Return info about game scoring setup; can be overridden by games."""
        return cls.scoreconfig if cls.scoreconfig is not None else ScoreConfig()

    @classmethod
    def getname(cls) -> str:
        """Return a str name for this game type.

        This default implementation simply returns the 'name' class attr.
        """
        return cls.name if cls.name is not None else 'Untitled Game'

    @classmethod
    def get_display_string(cls, settings: dict | None = None) -> babase.Lstr:
        """Return a descriptive name for this game/settings combo.

        Subclasses should override getname(); not this.
        """
        name = babase.Lstr(translate=('gameNames', cls.getname()))

        # A few substitutions for 'Epic', 'Solo' etc. modes.
        # FIXME: Should provide a way for game types to define filters of
        #  their own and should not rely on hard-coded settings names.
        if settings is not None:
            if 'Solo Mode' in settings and settings['Solo Mode']:
                name = babase.Lstr(
                    resource='soloNameFilterText', subs=[('${NAME}', name)]
                )
            if 'Epic Mode' in settings and settings['Epic Mode']:
                name = babase.Lstr(
                    resource='epicNameFilterText', subs=[('${NAME}', name)]
                )

        return name

    @classmethod
    def get_team_display_string(cls, name: str) -> babase.Lstr:
        """Given a team name, returns a localized version of it."""
        return babase.Lstr(translate=('teamNames', name))

    @classmethod
    def get_description(cls, sessiontype: type[bascenev1.Session]) -> str:
        """Get a str description of this game type.

        The default implementation simply returns the 'description' class var.
        Classes which want to change their description depending on the session
        can override this method.
        """
        del sessiontype  # Unused arg.
        return cls.description if cls.description is not None else ''

    @classmethod
    def get_description_display_string(
        cls, sessiontype: type[bascenev1.Session]
    ) -> babase.Lstr:
        """Return a translated version of get_description().

        Sub-classes should override get_description(); not this.
        """
        description = cls.get_description(sessiontype)
        return babase.Lstr(translate=('gameDescriptions', description))

    @classmethod
    def get_available_settings(
        cls, sessiontype: type[bascenev1.Session]
    ) -> list[bascenev1.Setting]:
        """Return a list of settings relevant to this game type when
        running under the provided session type.
        """
        del sessiontype  # Unused arg.
        return [] if cls.available_settings is None else cls.available_settings

    @classmethod
    def get_supported_maps(
        cls, sessiontype: type[bascenev1.Session]
    ) -> list[str]:
        """
        Called by the default bascenev1.GameActivity.create_settings_ui()
        implementation; should return a list of map names valid
        for this game-type for the given bascenev1.Session type.
        """
        del sessiontype  # Unused arg.
        assert babase.app.classic is not None
        return babase.app.classic.getmaps('melee')

    @classmethod
    def get_settings_display_string(cls, config: dict[str, Any]) -> babase.Lstr:
        """Given a game config dict, return a short description for it.

        This is used when viewing game-lists or showing what game
        is up next in a series.
        """
        name = cls.get_display_string(config['settings'])

        # In newer configs, map is in settings; it used to be in the
        # config root.
        if 'map' in config['settings']:
            sval = babase.Lstr(
                value='${NAME} @ ${MAP}',
                subs=[
                    ('${NAME}', name),
                    (
                        '${MAP}',
                        _map.get_map_display_string(
                            _map.get_filtered_map_name(
                                config['settings']['map']
                            )
                        ),
                    ),
                ],
            )
        elif 'map' in config:
            sval = babase.Lstr(
                value='${NAME} @ ${MAP}',
                subs=[
                    ('${NAME}', name),
                    (
                        '${MAP}',
                        _map.get_map_display_string(
                            _map.get_filtered_map_name(config['map'])
                        ),
                    ),
                ],
            )
        else:
            print('invalid game config - expected map entry under settings')
            sval = babase.Lstr(value='???')
        return sval

    @classmethod
    def supports_session_type(
        cls, sessiontype: type[bascenev1.Session]
    ) -> bool:
        """Return whether this game supports the provided Session type."""
        from bascenev1._multiteamsession import MultiTeamSession

        # By default, games support any versus mode
        return issubclass(sessiontype, MultiTeamSession)

    def __init__(self, settings: dict):
        """Instantiate the Activity."""
        super().__init__(settings)

        plus = babase.app.plus

        # Holds some flattened info about the player set at the point
        # when on_begin() is called.
        self.initialplayerinfos: list[bascenev1.PlayerInfo] | None = None

        # Go ahead and get our map loading.
        self._map_type = _map.get_map_class(self._calc_map_name(settings))

        self._spawn_sound = _bascenev1.getsound('spawn')
        self._map_type.preload()
        self._map: bascenev1.Map | None = None
        self._powerup_drop_timer: bascenev1.Timer | None = None
        self._tnt_spawners: dict[int, TNTSpawner] | None = None
        self._tnt_drop_timer: bascenev1.Timer | None = None
        self._game_scoreboard_name_text: bascenev1.Actor | None = None
        self._game_scoreboard_description_text: bascenev1.Actor | None = None
        self._standard_time_limit_time: int | None = None
        self._standard_time_limit_timer: bascenev1.Timer | None = None
        self._standard_time_limit_text: bascenev1.NodeActor | None = None
        self._standard_time_limit_text_input: bascenev1.NodeActor | None = None
        self._tournament_time_limit: int | None = None
        self._tournament_time_limit_timer: bascenev1.BaseTimer | None = None
        self._tournament_time_limit_title_text: bascenev1.NodeActor | None = (
            None
        )
        self._tournament_time_limit_text: bascenev1.NodeActor | None = None
        self._tournament_time_limit_text_input: bascenev1.NodeActor | None = (
            None
        )
        self._zoom_message_times: dict[int, float] = {}
        self._is_waiting_for_continue = False

        self._continue_cost = (
            25
            if plus is None
            else plus.get_v1_account_misc_read_val('continueStartCost', 25)
        )
        self._continue_cost_mult = (
            2
            if plus is None
            else plus.get_v1_account_misc_read_val('continuesMult', 2)
        )
        self._continue_cost_offset = (
            0
            if plus is None
            else plus.get_v1_account_misc_read_val('continuesOffset', 0)
        )

        self._support_text: bascenev1.Node | None = None
        self._top_score_text: bascenev1.Node | None = None
        self._social_texts: list[bascenev1.Node] = []
        self._theme_text: bascenev1.Node | None = None
        self._server_name_text: bascenev1.Node | None = None
        self.active_theme: themes.Theme | None = None
        self.force_simple_themes: bool = True
        self.active_modifiers: list[modifiers.Modifier] = []
        self._is_on_overtime: bool = False

    @property
    def map(self) -> _map.Map:
        """The map being used for this game.

        Raises a bascenev1.MapNotFoundError if the map does not currently
        exist.
        """
        if self._map is None:
            raise babase.MapNotFoundError
        return self._map

    def get_instance_display_string(self) -> babase.Lstr:
        """Return a name for this particular game instance."""
        return self.get_display_string(self.settings_raw)

    # noinspection PyUnresolvedReferences
    def get_instance_scoreboard_display_string(self) -> babase.Lstr:
        """Return a name for this particular game instance.

        This name is used above the game scoreboard in the corner
        of the screen, so it should be as concise as possible.
        """
        # If we're in a co-op session, use the level name.
        # FIXME: Should clean this up.
        try:
            from bascenev1._coopsession import CoopSession

            if isinstance(self.session, CoopSession):
                campaign = self.session.campaign
                assert campaign is not None
                return campaign.getlevel(
                    self.session.campaign_level_name
                ).displayname
        except Exception:
            logging.exception('Error getting campaign level name.')
        return self.get_instance_display_string()

    def get_instance_description(self) -> str | Sequence:
        """Return a description for this game instance, in English.

        This is shown in the center of the screen below the game name at the
        start of a game. It should start with a capital letter and end with a
        period, and can be a bit more verbose than the version returned by
        get_instance_description_short().

        Note that translation is applied by looking up the specific returned
        value as a key, so the number of returned variations should be limited;
        ideally just one or two. To include arbitrary values in the
        description, you can return a sequence of values in the following
        form instead of just a string:

        # This will give us something like 'Score 3 goals.' in English
        # and can properly translate to 'Anota 3 goles.' in Spanish.
        # If we just returned the string 'Score 3 Goals' here, there would
        # have to be a translation entry for each specific number. ew.
        return ['Score ${ARG1} goals.', self.settings_raw['Score to Win']]

        This way the first string can be consistently translated, with any arg
        values then substituted into the result. ${ARG1} will be replaced with
        the first value, ${ARG2} with the second, etc.
        """
        return self.get_description(type(self.session))

    def get_instance_description_short(self) -> str | Sequence:
        """Return a short description for this game instance in English.

        This description is used above the game scoreboard in the
        corner of the screen, so it should be as concise as possible.
        It should be lowercase and should not contain periods or other
        punctuation.

        Note that translation is applied by looking up the specific returned
        value as a key, so the number of returned variations should be limited;
        ideally just one or two. To include arbitrary values in the
        description, you can return a sequence of values in the following form
        instead of just a string:

        # This will give us something like 'score 3 goals' in English
        # and can properly translate to 'anota 3 goles' in Spanish.
        # If we just returned the string 'score 3 goals' here, there would
        # have to be a translation entry for each specific number. ew.
        return ['score ${ARG1} goals', self.settings_raw['Score to Win']]

        This way the first string can be consistently translated, with any arg
        values then substituted into the result. ${ARG1} will be replaced
        with the first value, ${ARG2} with the second, etc.

        """
        return ''

    def on_transition_in(self) -> None:
        super().on_transition_in()

        # Make our map.
        self._map = self._map_type()

        # Make NoneTheme adapt to this activity's globalsnode
        themes.NoneTheme.adapt()

        self.apply_modifiers(initial=True)
        self.decorate()

        # Give the world a chance to override the music.
        # (for maps and themes)
        theme_music = self.active_theme.music_type
        map_music = self._map_type.get_music_type()
        music = theme_music or map_music or self.default_music

        if music is not None:
            _music.setmusic(music)

        if babase.app.env.gui:
            bui.set_party_icon_always_visible(True)

    def on_continue(self) -> None:
        """
        This is called if a game supports and offers a continue and the player
        accepts.  In this case the player should be given an extra life or
        whatever is relevant to keep the game going.
        """

    def _continue_choice(self, do_continue: bool) -> None:
        plus = babase.app.plus
        assert plus is not None
        self._is_waiting_for_continue = False
        if self.has_ended():
            return
        with self.context:
            if do_continue:
                _bascenev1.getsound('shieldUp').play()
                _bascenev1.getsound('cashRegister').play()
                plus.add_v1_account_transaction(
                    {'type': 'CONTINUE', 'cost': self._continue_cost}
                )
                if plus is not None:
                    plus.run_v1_account_transactions()
                self._continue_cost = (
                    self._continue_cost * self._continue_cost_mult
                    + self._continue_cost_offset
                )
                self.on_continue()
            else:
                self.end_game()

    def is_waiting_for_continue(self) -> bool:
        """Returns whether or not this activity is currently waiting for the
        player to continue (or timeout)"""
        return self._is_waiting_for_continue

    def continue_or_end_game(self) -> None:
        """If continues are allowed, prompts the player to purchase a continue
        and calls either end_game or continue_game depending on the result
        """
        # pylint: disable=too-many-nested-blocks
        # pylint: disable=cyclic-import
        from bascenev1._coopsession import CoopSession

        classic = babase.app.classic
        assert classic is not None
        continues_window = classic.continues_window

        # Turning these off. I want to migrate towards monetization that
        # feels less pay-to-win-ish.
        allow_continues = False

        plus = babase.app.plus
        try:
            if (
                plus is not None
                and plus.get_v1_account_misc_read_val('enableContinues', False)
                and allow_continues
            ):
                session = self.session

                # We only support continuing in non-tournament games.
                tournament_id = session.tournament_id
                if tournament_id is None:
                    # We currently only support continuing in sequential
                    # co-op campaigns.
                    if isinstance(session, CoopSession):
                        assert session.campaign is not None
                        if session.campaign.sequential:
                            gnode = self.globalsnode

                            # Only attempt this if we're not currently paused
                            # and there appears to be no UI.
                            assert babase.app.classic is not None
                            hmmw = babase.app.ui_v1.has_main_menu_window()
                            if not gnode.paused and not hmmw:
                                self._is_waiting_for_continue = True
                                with babase.ContextRef.empty():
                                    babase.apptimer(
                                        0.5,
                                        lambda: continues_window(
                                            self,
                                            self._continue_cost,
                                            continue_call=babase.WeakCall(
                                                self._continue_choice, True
                                            ),
                                            cancel_call=babase.WeakCall(
                                                self._continue_choice, False
                                            ),
                                        ),
                                    )
                                return

        except Exception:
            logging.exception('Error handling continues.')

        self.end_game()

    def on_begin(self) -> None:
        super().on_begin()

        if babase.app.classic is not None:
            babase.app.classic.game_begin_analytics()

        # We don't do this in on_transition_in because it may depend on
        # players/teams which aren't available until now.
        _bascenev1.timer(0.001, self._show_scoreboard_info)
        _bascenev1.timer(1.0, self._show_info)
        _bascenev1.timer(2.5, self._show_tip)

        # Store some basic info about players present at start time.
        self.initialplayerinfos = [
            PlayerInfo(name=p.getname(full=True), character=p.character)
            for p in self.players
        ]

        # Sort this by name so high score lists/etc will be consistent
        # regardless of player join order.
        self.initialplayerinfos.sort(key=lambda x: x.name)

        # If this is a tournament, query info about it such as how much
        # time is left.
        tournament_id = self.session.tournament_id
        if tournament_id is not None:
            assert babase.app.plus is not None
            babase.app.plus.tournament_query(
                args={
                    'tournamentIDs': [tournament_id],
                    'source': 'in-game time remaining query',
                },
                callback=babase.WeakCall(self._on_tournament_query_response),
            )

    def _on_tournament_query_response(
        self, data: dict[str, Any] | None
    ) -> None:
        if data is not None:
            data_t = data['t']  # This used to be the whole payload.

            # Keep our cached tourney info up to date
            assert babase.app.classic is not None
            babase.app.classic.accounts.cache_tournament_info(data_t)
            self._setup_tournament_time_limit(
                max(5, data_t[0]['timeRemaining'])
            )

    def on_player_join(self, player: PlayerT) -> None:
        super().on_player_join(player)

        # By default, just spawn a dude.
        self.spawn_player(player)

    def handlemessage(self, msg: Any) -> Any:
        if isinstance(msg, PlayerDiedMessage):
            # pylint: disable=cyclic-import
            from bascenev1lib.actor.spaz import Spaz

            player = msg.getplayer(self.playertype)
            killer = msg.getkillerplayer(self.playertype)

            # Inform our stats of the demise.
            self.stats.player_was_killed(
                player, killed=msg.killed, killer=killer
            )

            # Award the killer points if he's on a different team.
            # FIXME: This should not be linked to Spaz actors.
            # (should move get_death_points to Actor or make it a message)
            if killer and killer.team is not player.team:
                assert isinstance(killer.actor, Spaz)
                pts, importance = killer.actor.get_death_points(msg.how)
                if not self.has_ended():
                    self.stats.player_scored(
                        killer,
                        pts,
                        kill=True,
                        victim_player=player,
                        importance=importance,
                        showpoints=self.show_kill_points,
                    )
        else:
            return super().handlemessage(msg)
        return None

    def _show_scoreboard_info(self) -> None:
        """Create the game info display.

        This is the thing in the top left corner showing the name
        and short description of the game.
        """
        # pylint: disable=too-many-locals
        from bascenev1._freeforallsession import FreeForAllSession
        from bascenev1._gameutils import animate
        from bascenev1._nodeactor import NodeActor

        sb_name = self.get_instance_scoreboard_display_string()

        # The description can be either a string or a sequence with args
        # to swap in post-translation.
        sb_desc_in = self.get_instance_description_short()
        sb_desc_l: Sequence
        if isinstance(sb_desc_in, str):
            sb_desc_l = [sb_desc_in]  # handle simple string case
        else:
            sb_desc_l = sb_desc_in
        if not isinstance(sb_desc_l[0], str):
            raise TypeError('Invalid format for instance description.')

        is_empty = sb_desc_l[0] == ''
        subs = []
        for i in range(len(sb_desc_l) - 1):
            subs.append(('${ARG' + str(i + 1) + '}', str(sb_desc_l[i + 1])))
        translation = babase.Lstr(
            translate=('gameDescriptions', sb_desc_l[0]), subs=subs
        )
        sb_desc = translation
        vrmode = babase.app.env.vr
        yval = -34 if is_empty else -20
        yval -= 16
        sbpos = (
            (15, yval)
            if isinstance(self.session, FreeForAllSession)
            else (15, yval)
        )
        self._game_scoreboard_name_text = NodeActor(
            _bascenev1.newnode(
                'text',
                attrs={
                    'text': sb_name,
                    'maxwidth': 300,
                    'position': sbpos,
                    'h_attach': 'left',
                    'vr_depth': 10,
                    'v_attach': 'top',
                    'v_align': 'bottom',
                    'color': (1.0, 1.0, 1.0, 1.0),
                    'shadow': 1.0 if vrmode else 0.6,
                    'flatness': 1.0 if vrmode else 0.5,
                    'scale': 1.1,
                },
            )
        )

        assert self._game_scoreboard_name_text.node
        animate(
            self._game_scoreboard_name_text.node, 'opacity', {0: 0.0, 1.0: 1.0}
        )

        descpos = (
            (17, -44 + 10)
            if isinstance(self.session, FreeForAllSession)
            else (17, -44 + 10)
        )
        self._game_scoreboard_description_text = NodeActor(
            _bascenev1.newnode(
                'text',
                attrs={
                    'text': sb_desc,
                    'maxwidth': 480,
                    'position': descpos,
                    'scale': 0.7,
                    'h_attach': 'left',
                    'v_attach': 'top',
                    'v_align': 'top',
                    'shadow': 1.0 if vrmode else 0.7,
                    'flatness': 1.0 if vrmode else 0.8,
                    'color': (1, 1, 1, 1) if vrmode else (0.9, 0.9, 0.9, 1.0),
                },
            )
        )

        assert self._game_scoreboard_description_text.node
        animate(
            self._game_scoreboard_description_text.node,
            'opacity',
            {0: 0.0, 1.0: 1.0},
        )

    def _show_info(self) -> None:
        """Show the game description."""
        from bascenev1._gameutils import animate
        from bascenev1lib.actor.zoomtext import ZoomText

        name = self.get_instance_display_string()
        ZoomText(
            name,
            maxwidth=800,
            lifespan=2.5,
            jitter=2.0,
            position=(0, 180),
            flash=False,
            color=(0.93 * 1.25, 0.9 * 1.25, 1.0 * 1.25),
            trailcolor=(0.15, 0.05, 1.0, 0.0),
        ).autoretain()
        _bascenev1.timer(0.2, _bascenev1.getsound('gong').play)
        # _bascenev1.timer(
        #     0.2, Call(_bascenev1.playsound, _bascenev1.getsound('gong'))
        # )

        # The description can be either a string or a sequence with args
        # to swap in post-translation.
        desc_in = self.get_instance_description()
        desc_l: Sequence
        if isinstance(desc_in, str):
            desc_l = [desc_in]  # handle simple string case
        else:
            desc_l = desc_in
        if not isinstance(desc_l[0], str):
            raise TypeError('Invalid format for instance description')
        subs = []
        for i in range(len(desc_l) - 1):
            subs.append(('${ARG' + str(i + 1) + '}', str(desc_l[i + 1])))
        translation = babase.Lstr(
            translate=('gameDescriptions', desc_l[0]), subs=subs
        )

        # Do some standard filters (epic mode, etc).
        if self.settings_raw.get('Epic Mode', False):
            translation = babase.Lstr(
                resource='epicDescriptionFilterText',
                subs=[('${DESCRIPTION}', translation)],
            )
        vrmode = babase.app.env.vr
        dnode = _bascenev1.newnode(
            'text',
            attrs={
                'v_attach': 'center',
                'h_attach': 'center',
                'h_align': 'center',
                'color': (1, 1, 1, 1),
                'shadow': 1.0 if vrmode else 0.5,
                'flatness': 1.0 if vrmode else 0.5,
                'vr_depth': -30,
                'position': (0, 80),
                'scale': 1.2,
                'maxwidth': 700,
                'text': translation,
            },
        )
        cnode = _bascenev1.newnode(
            'combine',
            owner=dnode,
            attrs={'input0': 1.0, 'input1': 1.0, 'input2': 1.0, 'size': 4},
        )
        cnode.connectattr('output', dnode, 'color')
        keys = {0.5: 0, 1.0: 1.0, 2.5: 1.0, 4.0: 0.0}
        animate(cnode, 'input3', keys)
        _bascenev1.timer(4.0, dnode.delete)

    def _show_tip(self) -> None:
        # pylint: disable=too-many-locals
        from bascenev1._gameutils import animate, GameTip

        # If there's any tips left on the list, display one.
        if self.tips:
            tip = self.tips.pop(random.randrange(len(self.tips)))
            tip_title = babase.Lstr(
                value='${A}:', subs=[('${A}', babase.Lstr(resource='tipText'))]
            )
            icon: bascenev1.Texture | None = None
            sound: bascenev1.Sound | None = None
            if isinstance(tip, GameTip):
                icon = tip.icon
                sound = tip.sound
                tip = tip.text
                assert isinstance(tip, str)

            # Do a few substitutions.
            tip_lstr = babase.Lstr(
                translate=('tips', tip),
                subs=[
                    ('${PICKUP}', babase.charstr(babase.SpecialChar.TOP_BUTTON))
                ],
            )
            base_position = (75, 50)
            tip_scale = 0.8
            tip_title_scale = 1.2
            vrmode = babase.app.env.vr

            t_offs = -350.0
            tnode = _bascenev1.newnode(
                'text',
                attrs={
                    'text': tip_lstr,
                    'scale': tip_scale,
                    'maxwidth': 900,
                    'position': (base_position[0] + t_offs, base_position[1]),
                    'h_align': 'left',
                    'vr_depth': 300,
                    'shadow': 1.0 if vrmode else 0.5,
                    'flatness': 1.0 if vrmode else 0.5,
                    'v_align': 'center',
                    'v_attach': 'bottom',
                },
            )
            t2pos = (
                base_position[0] + t_offs - (20 if icon is None else 82),
                base_position[1] + 2,
            )
            t2node = _bascenev1.newnode(
                'text',
                owner=tnode,
                attrs={
                    'text': tip_title,
                    'scale': tip_title_scale,
                    'position': t2pos,
                    'h_align': 'right',
                    'vr_depth': 300,
                    'shadow': 1.0 if vrmode else 0.5,
                    'flatness': 1.0 if vrmode else 0.5,
                    'maxwidth': 140,
                    'v_align': 'center',
                    'v_attach': 'bottom',
                },
            )
            if icon is not None:
                ipos = (base_position[0] + t_offs - 40, base_position[1] + 1)
                img = _bascenev1.newnode(
                    'image',
                    attrs={
                        'texture': icon,
                        'position': ipos,
                        'scale': (50, 50),
                        'opacity': 1.0,
                        'vr_depth': 315,
                        'color': (1, 1, 1),
                        'absolute_scale': True,
                        'attach': 'bottomCenter',
                    },
                )
                animate(img, 'opacity', {0: 0, 1.0: 1, 4.0: 1, 5.0: 0})
                _bascenev1.timer(5.0, img.delete)
            if sound is not None:
                sound.play()

            combine = _bascenev1.newnode(
                'combine',
                owner=tnode,
                attrs={'input0': 1.0, 'input1': 0.8, 'input2': 1.0, 'size': 4},
            )
            combine.connectattr('output', tnode, 'color')
            combine.connectattr('output', t2node, 'color')
            animate(combine, 'input3', {0: 0, 1.0: 1, 4.0: 1, 5.0: 0})
            _bascenev1.timer(5.0, tnode.delete)

    def end(
        self, results: Any = None, delay: float = 0.0, force: bool = False
    ) -> None:
        if self.active_theme:
            self.active_theme.handlemessage(DieMessage)
        for modifier in self.active_modifiers:
            modifier.handlemessage(DieMessage(True))

        from bascenev1._gameresults import GameResults

        # If results is a standard team-game-results, associate it with us
        # so it can grab our score prefs.
        if isinstance(results, GameResults):
            results.set_game(self)

        # If we had a standard time-limit that had not expired, stop it so
        # it doesnt tick annoyingly.
        if (
            self._standard_time_limit_time is not None
            and self._standard_time_limit_time > 0
        ):
            self._standard_time_limit_timer = None
            self._standard_time_limit_text = None

        # Ditto with tournament time limits.
        if (
            self._tournament_time_limit is not None
            and self._tournament_time_limit > 0
        ):
            self._tournament_time_limit_timer = None
            self._tournament_time_limit_text = None
            self._tournament_time_limit_title_text = None

        super().end(results, delay, force)

    def end_game(self) -> None:
        """Tell the game to wrap up and call bascenev1.Activity.end().

        This method should be overridden by subclasses. A game should always
        be prepared to end and deliver results, even if there is no 'winner'
        yet; this way things like the standard time-limit
        (bascenev1.GameActivity.setup_standard_time_limit()) will work with
        the game.
        """
        print(
            'WARNING: default end_game() implementation called;'
            ' your game should override this.'
        )

    def respawn_player(
        self, player: PlayerT, respawn_time: float | None = None
    ) -> None:
        """
        Given a bascenev1.Player, sets up a standard respawn timer,
        along with the standard counter display, etc.
        At the end of the respawn period spawn_player() will
        be called if the Player still exists.
        An explicit 'respawn_time' can optionally be provided
        (in seconds).
        """
        # pylint: disable=cyclic-import

        assert player
        if respawn_time is None:
            teamsize = len(player.team.players)
            if teamsize == 1:
                respawn_time = 3.0
            elif teamsize == 2:
                respawn_time = 5.0
            elif teamsize == 3:
                respawn_time = 6.0
            else:
                respawn_time = 7.0

        # If this standard setting is present, factor it in.
        if 'Respawn Times' in self.settings_raw:
            respawn_time *= self.settings_raw['Respawn Times']

        # We want whole seconds.
        assert respawn_time is not None
        respawn_time = round(max(1.0, respawn_time), 0)

        if player.actor and not self.has_ended():
            from bascenev1lib.actor.respawnicon import RespawnIcon

            player.customdata['respawn_timer'] = _bascenev1.Timer(
                respawn_time,
                babase.WeakCall(self.spawn_player_if_exists, player),
            )
            player.customdata['respawn_icon'] = RespawnIcon(
                player, respawn_time
            )

    def spawn_player_if_exists(self, player: PlayerT) -> None:
        """
        A utility method which calls self.spawn_player() *only* if the
        bascenev1.Player provided still exists; handy for use in timers
        and whatnot.

        There is no need to override this; just override spawn_player().
        """
        if player:
            self.spawn_player(player)

    def spawn_player(self, player: PlayerT) -> bascenev1.Actor:
        """Spawn *something* for the provided bascenev1.Player.

        The default implementation simply calls spawn_player_spaz().
        """
        assert player  # Dead references should never be passed as args.

        return self.spawn_player_spaz(player)

    def spawn_player_spaz(
        self,
        player: PlayerT,
        position: Sequence[float] = (0, 0, 0),
        angle: float | None = None,
    ) -> PlayerSpaz:
        """Create and wire up a bascenev1.PlayerSpaz for the provided Player."""
        # pylint: disable=too-many-locals
        # pylint: disable=cyclic-import
        from bascenev1._gameutils import animate
        from bascenev1._coopsession import CoopSession
        from bascenev1lib.actor.playerspaz import PlayerSpaz

        name = player.getname()
        color = player.color
        highlight = player.highlight

        playerspaztype = getattr(player, 'playerspaztype', PlayerSpaz)
        if not issubclass(playerspaztype, PlayerSpaz):
            playerspaztype = PlayerSpaz

        light_color = babase.normalized_color(color)
        display_color = babase.safecolor(color, target_intensity=0.75)
        spaz = playerspaztype(
            color=color,
            highlight=highlight,
            character=player.character,
            player=player,
        )

        player.actor = spaz
        assert spaz.node

        # If this is co-op and we're on Courtyard or Runaround, add the
        # material that allows us to collide with the player-walls.
        # FIXME: Need to generalize this.
        if isinstance(self.session, CoopSession) and self.map.getname() in [
            'Courtyard',
            'Tower D',
        ]:
            mat = self.map.preloaddata['collide_with_wall_material']
            assert isinstance(spaz.node.materials, tuple)
            assert isinstance(spaz.node.roller_materials, tuple)
            spaz.node.materials += (mat,)
            spaz.node.roller_materials += (mat,)

        spaz.node.name = name
        spaz.node.name_color = display_color
        spaz.connect_controls_to_player()

        # Move to the stand position and add a flash of light.
        spaz.handlemessage(
            StandMessage(
                position, angle if angle is not None else random.uniform(0, 360)
            )
        )
        self._spawn_sound.play(1, position=spaz.node.position)
        light = _bascenev1.newnode('light', attrs={'color': light_color})
        spaz.node.connectattr('position', light, 'position')
        animate(light, 'intensity', {0: 0, 0.25: 1, 0.5: 0})
        _bascenev1.timer(0.5, light.delete)
        if babase.app.classic and babase.app.classic.server:
            spaz.give_ranks()
            spaz.give_alliances()
            spaz.give_cstms()
            spaz.give_leagues()
            spaz.give_tops()
            spaz.give_usernames()
            spaz.equip()
        return spaz

    def setup_standard_powerup_drops(self, enable_tnt: bool = True) -> None:
        """Create standard powerup drops for the current map."""
        # pylint: disable=cyclic-import
        from bascenev1lib.actor.powerupbox import DEFAULT_POWERUP_INTERVAL

        self._powerup_drop_timer = _bascenev1.Timer(
            DEFAULT_POWERUP_INTERVAL,
            babase.WeakCall(self._standard_drop_powerups),
            repeat=True,
        )
        self._standard_drop_powerups()
        if enable_tnt:
            self._tnt_spawners = {}
            self._setup_standard_tnt_drops()

    def _standard_drop_powerup(self, index: int, expire: bool = True) -> None:
        # pylint: disable=cyclic-import
        from bascenev1lib.actor.powerupbox import PowerupBox, PowerupBoxFactory

        PowerupBox(
            position=self.map.powerup_spawn_points[index],
            poweruptype=PowerupBoxFactory.get().get_random_powerup_type(),
            expire=expire,
        ).autoretain()

    def _standard_drop_powerups(self) -> None:
        """Standard powerup drop."""

        # Drop one powerup per point.
        points = self.map.powerup_spawn_points
        for i in range(len(points)):
            _bascenev1.timer(
                i * 0.4, babase.WeakCall(self._standard_drop_powerup, i)
            )

    def _setup_standard_tnt_drops(self) -> None:
        """Standard tnt drop."""
        # pylint: disable=cyclic-import
        from bascenev1lib.actor.bomb import TNTSpawner

        for i, point in enumerate(self.map.tnt_points):
            assert self._tnt_spawners is not None
            if self._tnt_spawners.get(i) is None:
                self._tnt_spawners[i] = TNTSpawner(point)

    def setup_standard_time_limit(self, duration: float) -> None:
        """
        Create a standard game time-limit given the provided
        duration in seconds.
        This will be displayed at the top of the screen.
        If the time-limit expires, end_game() will be called.
        """
        from bascenev1._nodeactor import NodeActor

        if duration <= 0.0:
            return
        self._standard_time_limit_time = int(duration)
        self._standard_time_limit_timer = _bascenev1.Timer(
            1.0, babase.WeakCall(self._standard_time_limit_tick), repeat=True
        )
        self._standard_time_limit_text = NodeActor(
            _bascenev1.newnode(
                'text',
                attrs={
                    'v_attach': 'top',
                    'h_attach': 'center',
                    'h_align': 'left',
                    'color': (
                        (0.5, 0.5, 1.0, 0.5)
                        if self._is_meeting_overtime_conditions
                        else (1.0, 1.0, 1.0, 0.5)
                    ),
                    'position': (-25, -30),
                    'flatness': 1.0,
                    'scale': 0.9,
                },
            )
        )
        self._standard_time_limit_text_input = NodeActor(
            _bascenev1.newnode(
                'timedisplay', attrs={'time2': duration * 1000, 'timemin': 0}
            )
        )
        self.globalsnode.connectattr(
            'time', self._standard_time_limit_text_input.node, 'time1'
        )
        assert self._standard_time_limit_text_input.node
        assert self._standard_time_limit_text.node
        self._standard_time_limit_text_input.node.connectattr(
            'output', self._standard_time_limit_text.node, 'text'
        )

    def _standard_time_limit_tick(self) -> None:
        from bascenev1._gameutils import animate

        assert self._standard_time_limit_time is not None
        self._standard_time_limit_time -= 1
        assert self._standard_time_limit_text is not None
        assert self._standard_time_limit_text.node
        self._standard_time_limit_text.node.color = (
            (0.5, 0.5, 1.0, 0.5)
            if self._is_meeting_overtime_conditions
            else (1.0, 1.0, 1.0, 0.5)
        )
        if self._standard_time_limit_time <= 10:
            if self._standard_time_limit_time == 10:
                self._standard_time_limit_text.node.scale = 1.3
                self._standard_time_limit_text.node.position = (-30, -45)
            cnode = _bascenev1.newnode(
                'combine',
                owner=self._standard_time_limit_text.node,
                attrs={'size': 4},
            )
            cnode.connectattr(
                'output', self._standard_time_limit_text.node, 'color'
            )
            if self._is_meeting_overtime_conditions:
                animate(cnode, 'input0', {0: 0.1, 0.15: 0.0}, loop=True)
                animate(cnode, 'input1', {0: 1.0, 0.15: 0.5}, loop=True)
                animate(cnode, 'input2', {0: 1.0, 0.15: 1.0}, loop=True)
            else:
                animate(cnode, 'input0', {0: 1, 0.15: 1}, loop=True)
                animate(cnode, 'input1', {0: 1, 0.15: 0.5}, loop=True)
                animate(cnode, 'input2', {0: 0.1, 0.15: 0.0}, loop=True)
            cnode.input3 = 1.0
            _bascenev1.getsound('tick').play()
        if self._standard_time_limit_time <= 0:
            self._standard_time_limit_timer = None
            if self._is_meeting_overtime_conditions:
                from bascenev1lib.actor.zoomtext import ZoomText

                self.overtime()
                self.active_theme.overtime()
                self._is_on_overtime = True

                self._standard_time_limit_text = None
                self.globalsnode.paused = True
                _bascenev1.basetimer(
                    0.7, babase.Call(setattr, self.globalsnode, 'paused', False)
                )
                ZoomText(
                    'OVERTIME',
                    lifespan=0.7,
                    color=(1.0, 1.0, 1.0),
                    jitter=4.0,
                    trailcolor=(0.0, 0.0, 1.0, 0.0),
                    scale=2.0,
                    base=True,
                ).autoretain()
                _music.setmusic(_music.MusicType.OVERTIME)
                with self.session.context:
                    vrmode = babase.app.env.vr
                    dnode = _bascenev1.newnode(
                        'text',
                        attrs={
                            'v_attach': 'center',
                            'h_attach': 'center',
                            'h_align': 'center',
                            'color': (1, 1, 1, 1),
                            'shadow': 1.0 if vrmode else 0.5,
                            'flatness': 1.0 if vrmode else 0.5,
                            'vr_depth': -30,
                            'position': (0, -160),
                            'scale': 1.2,
                            'maxwidth': 700,
                            'text': self.overtime_description,
                        },
                    )
                    cnode = _bascenev1.newnode(
                        'combine',
                        owner=dnode,
                        attrs={
                            'input0': 1.0,
                            'input1': 1.0,
                            'input2': 1.0,
                            'size': 4,
                        },
                    )
                    cnode.connectattr('output', dnode, 'color')
                    keys = {0.1: 0.0, 0.2: 1.0, 1.0: 1.0, 1.5: 0.0}
                    animate(cnode, 'input3', keys, session=True)
                    _bascenev1.timer(1.5, dnode.delete)
                node = _bascenev1.newnode(
                    'text',
                    attrs={
                        'v_attach': 'top',
                        'v_align': 'top',
                        'h_attach': 'center',
                        'h_align': 'center',
                        'color': (1, 0.7, 0, 1),
                        'position': (0, -5),
                        'scale': 1.2,
                        'text': 'OVERTIME',
                    },
                )
                cnode = _bascenev1.newnode(
                    'combine', owner=node, attrs={'size': 4}
                )
                cnode.connectattr('output', node, 'color')
                animate(cnode, 'input0', {0: 0.1, 0.15: 0.0}, loop=True)
                animate(cnode, 'input1', {0: 1.0, 0.15: 0.5}, loop=True)
                animate(cnode, 'input2', {0: 1.0, 0.15: 1.0}, loop=True)
                cnode.input3 = 1.0
            else:
                self.end_game()
                node = _bascenev1.newnode(
                    'text',
                    attrs={
                        'v_attach': 'top',
                        'h_attach': 'center',
                        'h_align': 'center',
                        'color': (1, 0.7, 0, 1),
                        'position': (0, -90),
                        'scale': 1.2,
                        'text': babase.Lstr(resource='timeExpiredText'),
                    },
                )
                _bascenev1.getsound('refWhistle').play()
            animate(node, 'scale', {0.0: 0.0, 0.1: 1.4, 0.15: 1.2})

    def _setup_tournament_time_limit(self, duration: float) -> None:
        """
        Create a tournament game time-limit given the provided
        duration in seconds.
        This will be displayed at the top of the screen.
        If the time-limit expires, end_game() will be called.
        """
        from bascenev1._nodeactor import NodeActor

        if duration <= 0.0:
            return
        self._tournament_time_limit = int(duration)

        # We want this timer to match the server's time as close as possible,
        # so lets go with base-time. Theoretically we should do real-time but
        # then we have to mess with contexts and whatnot since its currently
        # not available in activity contexts. :-/
        self._tournament_time_limit_timer = _bascenev1.BaseTimer(
            1.0, babase.WeakCall(self._tournament_time_limit_tick), repeat=True
        )
        self._tournament_time_limit_title_text = NodeActor(
            _bascenev1.newnode(
                'text',
                attrs={
                    'v_attach': 'bottom',
                    'h_attach': 'left',
                    'h_align': 'center',
                    'v_align': 'center',
                    'vr_depth': 300,
                    'maxwidth': 100,
                    'color': (1.0, 1.0, 1.0, 0.5),
                    'position': (60, 50),
                    'flatness': 1.0,
                    'scale': 0.5,
                    'text': babase.Lstr(resource='tournamentText'),
                },
            )
        )
        self._tournament_time_limit_text = NodeActor(
            _bascenev1.newnode(
                'text',
                attrs={
                    'v_attach': 'bottom',
                    'h_attach': 'left',
                    'h_align': 'center',
                    'v_align': 'center',
                    'vr_depth': 300,
                    'maxwidth': 100,
                    'color': (1.0, 1.0, 1.0, 0.5),
                    'position': (60, 30),
                    'flatness': 1.0,
                    'scale': 0.9,
                },
            )
        )
        self._tournament_time_limit_text_input = NodeActor(
            _bascenev1.newnode(
                'timedisplay',
                attrs={
                    'timemin': 0,
                    'time2': self._tournament_time_limit * 1000,
                },
            )
        )
        assert self._tournament_time_limit_text.node
        assert self._tournament_time_limit_text_input.node
        self._tournament_time_limit_text_input.node.connectattr(
            'output', self._tournament_time_limit_text.node, 'text'
        )

    def _tournament_time_limit_tick(self) -> None:
        from bascenev1._gameutils import animate

        assert self._tournament_time_limit is not None
        self._tournament_time_limit -= 1
        if self._tournament_time_limit <= 10:
            if self._tournament_time_limit == 10:
                assert self._tournament_time_limit_title_text is not None
                assert self._tournament_time_limit_title_text.node
                assert self._tournament_time_limit_text is not None
                assert self._tournament_time_limit_text.node
                self._tournament_time_limit_title_text.node.scale = 1.0
                self._tournament_time_limit_text.node.scale = 1.3
                self._tournament_time_limit_title_text.node.position = (80, 85)
                self._tournament_time_limit_text.node.position = (80, 60)
                cnode = _bascenev1.newnode(
                    'combine',
                    owner=self._tournament_time_limit_text.node,
                    attrs={'size': 4},
                )
                cnode.connectattr(
                    'output',
                    self._tournament_time_limit_title_text.node,
                    'color',
                )
                cnode.connectattr(
                    'output', self._tournament_time_limit_text.node, 'color'
                )
                animate(cnode, 'input0', {0: 1, 0.15: 1}, loop=True)
                animate(cnode, 'input1', {0: 1, 0.15: 0.5}, loop=True)
                animate(cnode, 'input2', {0: 0.1, 0.15: 0.0}, loop=True)
                cnode.input3 = 1.0
            _bascenev1.getsound('tick').play()
        if self._tournament_time_limit <= 0:
            self._tournament_time_limit_timer = None
            self.end_game()
            tval = babase.Lstr(
                resource='tournamentTimeExpiredText',
                fallback_resource='timeExpiredText',
            )
            node = _bascenev1.newnode(
                'text',
                attrs={
                    'v_attach': 'top',
                    'h_attach': 'center',
                    'h_align': 'center',
                    'color': (1, 0.7, 0, 1),
                    'position': (0, -200),
                    'scale': 1.6,
                    'text': tval,
                },
            )
            _bascenev1.getsound('refWhistle').play()
            animate(node, 'scale', {0: 0.0, 0.1: 1.4, 0.15: 1.2})

        # Normally we just connect this to time, but since this is a bit of a
        # funky setup we just update it manually once per second.
        assert self._tournament_time_limit_text_input is not None
        assert self._tournament_time_limit_text_input.node
        self._tournament_time_limit_text_input.node.time2 = (
            self._tournament_time_limit * 1000
        )

    def show_zoom_message(
        self,
        message: babase.Lstr,
        color: Sequence[float] = (0.9, 0.4, 0.0),
        scale: float = 0.8,
        duration: float = 2.0,
        trail: bool = False,
    ) -> None:
        """Zooming text used to announce game names and winners."""
        # pylint: disable=cyclic-import
        from bascenev1lib.actor.zoomtext import ZoomText

        # Reserve a spot on the screen (in case we get multiple of these so
        # they don't overlap).
        i = 0
        cur_time = babase.apptime()
        while True:
            if (
                i not in self._zoom_message_times
                or self._zoom_message_times[i] < cur_time
            ):
                self._zoom_message_times[i] = cur_time + duration
                break
            i += 1
        ZoomText(
            message,
            lifespan=duration,
            jitter=2.0,
            position=(0, 200 - i * 100),
            scale=scale,
            maxwidth=800,
            trail=trail,
            color=color,
        ).autoretain()

    def _calc_map_name(self, settings: dict) -> str:
        map_name: str
        if 'map' in settings:
            map_name = settings['map']
        else:
            # If settings doesn't specify a map, pick a random one from the
            # list of supported ones.
            unowned_maps: list[str] = (
                babase.app.classic.store.get_unowned_maps()
                if babase.app.classic is not None
                else []
            )
            valid_maps: list[str] = [
                m
                for m in self.get_supported_maps(type(self.session))
                if m not in unowned_maps
            ]
            if not valid_maps:
                _bascenev1.broadcastmessage(
                    babase.Lstr(resource='noValidMapsErrorText')
                )
                raise RuntimeError('No valid maps')
            map_name = valid_maps[random.randrange(len(valid_maps))]
        return map_name

    def decorate(
        self,
        preset: themes.Theme | None = None,
        transition: bool = False,
    ) -> None:
        if self.active_theme:
            self.active_theme.handlemessage(DieMessage())
            self.active_theme = None
        if not preset:
            all_themes = []
            for cfgkey, theme in themes.THEME_DICT.items():
                default = True
                if cfgkey == 'At-The-End-of-Space Theme':
                    default = False
                if babase.app.config.get(cfgkey, default):
                    all_themes.append(theme)
            if len(all_themes) == 0:
                all_themes.append(themes.NoneTheme)
            preset = random.choice(all_themes)
        self.active_theme = preset(
            transition,
            self.map.get_def_bound_box('map_bounds'),
            not self.force_simple_themes,
        )
        if not self._theme_text:
            y = 0
            if (
                babase.app.classic
                and babase.app.classic.server
                and not self._server_name_text
            ):
                if babase.app.classic.server._config.support_text:
                    self._support_text = _bascenev1.newnode(
                        'text',
                        attrs={
                            'v_attach': 'bottom',
                            'h_attach': 'center',
                            'h_align': 'center',
                            'v_align': 'bottom',
                            'position': (0, y),
                            'scale': 0.55,
                            'shadow':1,
                            'text': (
                                babase.app.classic.server._config.support_text
                            ),
                        },
                    )
                    red = (1, 0.15, 0.15, 1)
                    orange = (1, 0.5, 0, 1)
                    yellow = (1, 1, 0, 1)
                    green = (0.2, 1, 0.2, 1)
                    blue = (0.1, 0.1, 1, 1)
                    purple = (0.5, 0.25, 1, 1)
                    animate_array(
                        self._support_text,
                        'color',
                        4,
                        {
                            0: red,
                            1: orange,
                            2: yellow,
                            3: green,
                            4: blue,
                            5: purple,
                            6: blue,
                            7: green,
                            8: yellow,
                            9: orange,
                            10: red,
                        },
                        True,
                    )
                    y += 20





                # counter = 120

                # while counter > 0:
                #    # time.sleep(60)
                #     counter -= 1  
        




                topscores = gdata.load(gdata.getpath('stops')) or {}
                topscores.setdefault('end', 0)
                end = topscores.pop('end') - time.time()

                if end >= 60:
                    end /= 60
                    endstr = ' minutes'
                    if end >= 60:
                        end /= 60
                        endstr = ' hours'
                        if end >= 24:
                            end /= 24
                            endstr = ' days'
                fend = ' (Resets in ' + str(round(end)) + endstr + ')'
 
                topscores = list(topscores.values())

                


                import bascenev1


                # ذخیره تابع اصلی on_begin
                original_on_begin = bascenev1.GameActivity.on_begin

                def on_begin(self: bascenev1.GameActivity) -> None:
                    original_on_begin(self)

                    # اگر on_launch_time قبلاً تنظیم نشده، مقداردهی اولیه کن
                    if not hasattr(self.session, 'on_launch_time'):
                        self.session.on_launch_time = time.time()

                    self.text = {}
                    self.timers = {}
                    self.show_server_restart_timer()

                def show_server_restart_timer(self) -> None:
                    self.text['restart_timer'] = bascenev1.newnode(
                        'text',
                        attrs={
                            'opacity': 1.168,
                            'scale': 0.75,
                            'position': (1160, 620),
                            'text': '',
                            'color': (146,248,148),
                            'h_align': 'left',
                            'v_align': 'bottom',
                            'h_attach': 'left',
                            'v_attach': 'bottom',
                            'shadow': 3,
                            'flatness': 100.0,
                        },
                    )
                    self.timers['update_server_time_timer'] = bascenev1.timer(
                        time=0.04,
                        call=self._update_server_time,
                        repeat=True,
                    )

                def _update_server_time(self) -> None:
                    # محاسبه زمان باقی‌مانده بر اساس زمان اولیه و config_restart
                    config_restart = babase.app.classic.server._config.unclean_exit_minutes * 60
                    self.end_time = self.session.on_launch_time + config_restart - (60 * 0.075)
                    remaining_time = int(self.end_time - time.time())

                    if remaining_time < 0.3:
                        self.text['restart_timer'].color = (1, 1, 1)
                        self.text['restart_timer'].text = 'RESTARTING...'
                    else:
                        current_hours = remaining_time // 3600
                        current_min = (remaining_time % 3600) // 60
                        current_sec = remaining_time % 60

                        percentage = (remaining_time / (self.end_time - self.session.on_launch_time + 5)) * 100

                        if percentage >= 75:
                            self.text['restart_timer'].color = (0, 1, 0)
                        elif percentage >= 50:
                            self.text['restart_timer'].color = (3, 2, 1)
                        elif percentage >= 25:
                            self.text['restart_timer'].color = (2, 2, 1)
                        elif percentage > 0:
                            self.text['restart_timer'].color = (2, 3, 3)
                        else:
                            self.text['restart_timer'].color = (1, 1, 1)

                        time_parts = []
                        if current_hours > 0:
                            time_parts.append(f'{current_hours}h')
                        if current_min > 0 or current_hours > 0:
                            time_parts.append(f'{current_min}m')
                        time_parts.append(f'{current_sec}s')

                        final_text = ' '.join(time_parts)
                        self.text['restart_timer'].text = final_text

                # جایگزینی توابع در GameActivity
                bascenev1.GameActivity.on_begin = on_begin
                bascenev1.GameActivity.show_server_restart_timer = show_server_restart_timer
                bascenev1.GameActivity._update_server_time = _update_server_time





                if len(topscores) != 0:
                    self._top_score_text = _bascenev1.newnode(
                        'text',
                        attrs={
                            'v_attach': 'bottom',
                            'h_attach': 'center',
                            'h_align': 'center',
                            'v_align': 'bottom',
                            'position': (250, 593),
                            'scale': 0.6,
                            'shadow':0.5,
                            'text': (
                                '🏆 TOP 1 SCORE: ' + str(topscores[0]) + '\n' +
                                '🥈 TOP 2 SCORE: ' + str(topscores[1]) + '\n' +
                                '🥉 TOP 3 SCORE: ' + str(topscores[2]) + '\n' +
                                fend
                            ),
                        },
                    )
                    animate_array(
                        self._top_score_text,
                        'color',
                        4,
                        {0: (1, 1, 1, 0), 1: (1, 1, 1, 1)},
                    )
                    y += 20
                for t, c in babase.app.classic.server._config.social_texts:
                    social_text = _bascenev1.newnode(
                        'text',
                        attrs={
                            'v_attach': 'bottom',
                            'h_attach': 'center',
                            'h_align': 'center',
                            'v_align': 'bottom',
                            'position': (-350, 650),
                            'scale': 0.7,
                            'shadow':1.25,
                            'text': t,
                        },
                    )
                    cs = list(c)
                    cs.append(0.0)
                    ce = list(c)
                    ce.append(1.0)
                    animate_array(social_text, 'color', 4, {0: cs, 1: ce})
                    y += 20
            if not isinstance(self.active_theme, themes.NoneTheme) or (
                babase.app.classic and babase.app.classic.server
            ):
                tint0 = list(self.active_theme.tint)
                tint1 = list(self.active_theme.tint)
                tint0.append(0)
                tint1.append(1)
                self._theme_text = _bascenev1.newnode(
                    'text',
                    attrs={
                        'v_attach': 'bottom',
                        'h_attach': 'center',
                        'h_align': 'center',
                        'v_align': 'bottom',
                        'position': (0, -200),
                        'scale': (
                            0.75
                            if babase.app.classic and babase.app.classic.server
                            else 1
                        ),
                        #'text': 'Theme: ' + str(self.active_theme.name),
                    },
                )
                animate_array(
                    self._theme_text,
                    'color',
                    4,
                    {0: tuple(tint0), 1: tuple(tint1)},
                )
                y += 20
            if (
                babase.app.classic
                and babase.app.classic.server
                and not self._server_name_text
            ):
                self._server_name_text = _bascenev1.newnode(
                    'text',
                    attrs={
                        'v_attach': 'bottom',
                        'h_attach': 'center',
                        'h_align': 'center',
                        'v_align': 'bottom',
                        'position': (0, 23),
                        'shadow':2,
                        'scale': 0.80,
                        'text': babase.app.classic.server._config.party_name,
                    },
                )
                animate_array(
                    self._server_name_text,
                    'color',
                    4,
                    {0: (1, 1, 1, 0), 1: (1, 1, 1, 1)},
                )
        # elif self._theme_text:
            # self._theme_text.text = 'Theme: ' + str(self.active_theme.name)

    def apply_modifiers(
        self,
        count: int | None = None,
        preset: list[modifiers.Modifier] | None = None,
        ultra: bool | None = None,
        initial: bool = False,
    ):
        count = count or babase.app.config.get('Modifier Count', 3)
        for amod in self.active_modifiers:
            amod.handlemessage(DieMessage())
        self.active_modifiers.clear()
        if not preset:
            preset = []
            for cfgkey, mod in modifiers.MOD_DICT.items():
                if babase.app.config.get(cfgkey, True):
                    preset.append(mod)
            random.shuffle(preset)
        for _ in range(count):
            mod = preset[0]
            preset.remove(mod)
            ultraloc = ultra
            if ultra is None:
                if (
                    babase.app.config.get('Allow Overcharged Modifiers', True)
                    and random.random() > 0.75
                ):
                    ultraloc = False
            elif mod is modifiers.RandomModifier:
                if ultra is True:
                    ultraloc = False
                else:
                    ultraloc = None
            mod = mod(ultraloc)
            for conflict in mod.conflicts:
                if conflict in preset:
                    preset.remove(conflict)
            self.active_modifiers.append(mod)
            if len(preset) == 0:
                break
        y = len(self.active_modifiers) * 25
        t = 1.0 if initial else 0.05
        with self.session.context if initial else self.context:
            for mod in self.active_modifiers:
                _bascenev1.timer(
                    t, babase.WeakCall(mod.make_badge, (0, y), initial)
                )
                y -= 50
                t += 1.0 if initial else 0.05
            if initial:
                _bascenev1.timer(
                    1.0, babase.Call(setattr, self.globalsnode, 'paused', True)
                )
                _bascenev1.timer(
                    t, babase.Call(setattr, self.globalsnode, 'paused', False)
                )

    def on_transition_out(self) -> None:
        super().on_transition_out()
        if babase.app.env.gui:
            bui.set_party_icon_always_visible(False)

    @property
    def _is_meeting_overtime_conditions(self) -> bool:
        """
        Whether our conditions for going OVERTIME are met or not, any gametype
        supporting OVERTIME should override this
        """
        return False

    @property
    def overtime_description(self) -> str:
        """
        A short description explaining this gametype's OVERTIME, it will be
        visible for a very short period of time before OVERTIME begins, any
        gametype supporting OVERTIME should override this
        """
        return ''

    def overtime(self) -> None:
        """
        This gets called when the standard time limit runs out while ending the
        game causes a draw, gametypes may choose to go "OVERTIME" instead of
        ending the activity
        """

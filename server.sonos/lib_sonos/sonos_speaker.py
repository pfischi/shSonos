# -*- coding: utf-8 -*-
from lib_sonos import utils
from soco.compat import quote_url
import queue
from soco.data_structures import DidlItem, to_didl_string
import logging
import requests
from lib_sonos.utils import NotifyList
from soco.alarms import get_alarms
import threading
import time
import json
from lib_sonos import udp_broker
from soco.snapshot import Snapshot
from soco.music_services import MusicService
from lib_sonos import definitions

try:
    import xml.etree.cElementTree as XML
except ImportError:
    import xml.etree.ElementTree as XML

logger = logging.getLogger('sonos_broker')

sonos_speakers = {}
_sonos_lock = threading.Lock()
event_queue = queue.Queue()

class SonosSpeaker(object):
    tts_local_mode = False
    local_folder = ''
    local_url = ''
    quota = 0

    @classmethod
    def set_tts(self, local_folder, local_url, quota, tts_local_mode):
        SonosSpeaker.local_folder = local_folder
        SonosSpeaker.local_url = local_url
        SonosSpeaker.quota = quota
        SonosSpeaker.tts_local_mode = tts_local_mode

    def __init__(self, soco):
        info = soco.get_speaker_info(timeout=5)
        self._snippet_queue_lock = threading.Lock()
        self.stop_tts = threading.Event()
        self._fade_in = False
        self._balance = 0
        self._saved_music_item = None
        self._zone_members = NotifyList()
        self._zone_members.register_callback(utils.WeakMethod(self, 'zone_member_changed'))
        self._dirty_properties = []
        self._soco = soco
        self._uid = self.soco.uid.lower()
        self._alarms = ''
        self._mute = 0
        self._track_uri = ''
        self._track_album = ''
        self._transport_actions = ''
        self._track_duration = "00:00:00"
        self._track_position = "00:00:00"
        self._streamtype = ''
        self._stop = 0
        self._play = 0
        self._pause = 0
        self._radio_station = ''
        self._radio_show = ''
        self._track_album_art = ''
        self._track_title = ''
        self._track_artist = ''
        self._led = 1
        self._max_volume = -1
        self._playlist_position = 0
        self._playlist_total_tracks = 0
        self._model = ''
        self._status = True
        self._metadata = ''
        self._sub_av_transport = None
        self._sub_rendering_control = None
        self._sub_zone_group = None
        self._sub_alarm = None
        self._sub_system_prop = None
        self._sub_device_prop = None
        self._properties_hash = None
        self._zone_coordinator = None
        self._additional_zone_members = ''
        self._volume = self.soco.volume
        self._bass = self.soco.bass
        self._nightmode = self.soco.night_mode
        self._treble = self.soco.treble
        self._loudness = self.soco.loudness
        self._playmode = self.soco.play_mode
        self._ip = self.soco.ip_address
        self._model = info['model_name']
        self._household_id = self.soco.household_id
        self._display_version = info['display_version']
        self._model_number = info['model_number']
        self._zone_icon = info['player_icon']
        self._zone_name = info['zone_name']
        self._serial_number = info['serial_number']
        self._software_version = info['software_version']
        self._hardware_version = info['hardware_version']
        self._mac_address = info['mac_address']
        self._wifi_state = self.get_wifi_state(force_refresh=True)
        self._sonos_playlists = self.soco.get_sonos_playlists()

        self.dirty_all()

    # SoCo instance ####################################################################################################

    @property
    def soco(self):

        """
        Returns the SoCo instance associated to the current Sonos speaker.
        :return: SoCo instance
        """
        return self._soco

    # MODEL ############################################################################################################

    @property
    def model(self):
        return self._model

    # MODEL NUMBER######################################################################################################

    @property
    def model_number(self):
        return self._model_number

    # DISPLAY VERSION ##################################################################################################

    @property
    def display_version(self):
        return self._display_version

    # METADATA #########################################################################################################

    @property
    def metadata(self):
        return self._metadata

    @metadata.setter
    def metadata(self, value):
        if self._metadata == value:
            return
        self._metadata = value

    # zone_coordinator #################################################################################################

    @property
    def zone_coordinator(self):
        return self._zone_coordinator

    @property
    def is_coordinator(self):
        if self == self.zone_coordinator:
            return True
        return False

    # EVENTS ###########################################################################################################

    @property
    def sub_device_properties(self):
        return self._sub_device_prop

    @property
    def sub_system_properties(self):
        return self._sub_system_prop

    @property
    def sub_av_transport(self):
        return self._sub_av_transport

    @property
    def sub_rendering_control(self):
        return self._sub_rendering_control

    @property
    def sub_zone_group(self):
        return self._sub_zone_group

    @property
    def sub_alarm(self):
        return self._sub_alarm

    # SERIAL ###########################################################################################################

    @property
    def serial_number(self):
        return self._serial_number

    # SOFTWARE VERSION #################################################################################################

    @property
    def software_version(self):
        return self._software_version

    # HARDWARE VERSION #################################################################################################

    @property
    def hardware_version(self):
        return self._hardware_version

    # HOUSEHOLD ID #####################################################################################################

    @property
    def household_id(self):
        return self._household_id

    # MAC ADDRESS ######################################################################################################

    @property
    def mac_address(self):
        return self._mac_address

    # LED ##############################################################################################################

    def get_led(self):
        return self._led

    def set_led(self, value, trigger_action=False, group_command=False):
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_led(value, trigger_action=True, group_command=False)
            self.soco.status_light = value
        if value == self._led:
            return
        self._led = value
        self.dirty_property('led')

    # BASS #############################################################################################################

    def get_bass(self):
        return self._bass

    def set_bass(self, value, trigger_action=False, group_command=False):
        bass = int(value)
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_bass(bass, trigger_action=True, group_command=False)
            self.soco.bass = bass
        if self._bass == bass:
            return
        self._bass = value
        self.dirty_property('bass')

    # TREBLE ###########################################################################################################

    def get_treble(self):
        return self._treble

    def set_treble(self, value, trigger_action=False, group_command=False):
        treble = int(value)
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_treble(treble, trigger_action=True, group_command=False)
            self.soco.treble = treble
        if self._treble == treble:
            return
        self._treble = treble
        self.dirty_property('treble')

    # LOUDNESS #########################################################################################################

    def get_loudness(self):
        return int(self._loudness)

    def set_loudness(self, value, trigger_action=False, group_command=False):
        loudness = int(value)
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_loudness(loudness, trigger_action=True, group_command=False)
            self.soco.loudness = loudness
        if self._loudness == loudness:
            return
        self._loudness = value
        self.dirty_property('loudness')

    # PLAYMODE #########################################################################################################

    def get_playmode(self):
        if not self.is_coordinator:
            logger.debug("forwarding playmode getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.playmode
        return self._playmode.lower()

    def set_playmode(self, value, trigger_action=False):
        if trigger_action:
            if not self.is_coordinator:
                logger.debug("forwarding playmode setter to coordinator with uid {uid}".
                             format(uid=self.zone_coordinator.uid))
                self.zone_coordinator.set_playmode(value, trigger_action)
            else:
                self.soco.play_mode = value
        if self._playmode == value:
            return
        self._playmode = value
        self.dirty_property('playmode')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('playmode')

    # ZONE NAME ########################################################################################################

    @property
    def zone_name(self):
        if not self.is_coordinator:
            logger.debug("forwarding zone_name getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.zone_name
        return self._zone_name

    # ZONE ICON ########################################################################################################

    @property
    def zone_icon(self):
        if not self.is_coordinator:
            logger.debug("forwarding zone_icon getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.zone_icon
        return self._zone_icon

    # ZONE MEMBERS #####################################################################################################

    @property
    def zone_members(self):
        return self._zone_members

    def zone_member_changed(self):
        self.current_state(group_command=True)
        # self.dirty_property('additional_zone_members')

    @property
    def additional_zone_members(self):
        """
        Returns all zone members (current speaker NOT included) as string, delimited by ','
        :return:
        """
        members = ','.join(str(speaker.uid) for speaker in self.zone_members)
        if not members:
            members = ''
        return members

    # IP ###############################################################################################################

    @property
    def ip(self):
        return self._ip

    # BALANCE ##########################################################################################################

    def get_balance(self):
        return self._balance

    def set_balance(self, balance, trigger_action=False, group_command=False):
        balance = int(balance)
        if not utils.check_balance_range(balance):
            return
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_volume(balance, trigger_action=True, group_command=False)
            if utils.check_balance_range(balance):
                self.soco.balance = balance
        if self._balance == balance:
            return
        self._balance = balance
        self.dirty_property('balance')

    # VOLUME ###########################################################################################################

    def get_volume(self):
        return self._volume

    def set_volume(self, volume, trigger_action=False, group_command=False):
        volume = int(volume)
        if self._volume == volume and not trigger_action:
            return
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_volume(volume, trigger_action=True, group_command=False)
            if utils.check_volume_range(volume):
                if utils.check_max_volume_exceeded(volume, self.max_volume):
                    volume = self.max_volume
                self.soco.volume = volume
        if self._volume == volume:
            return
        self._volume = volume
        self.dirty_property('volume')

    # VOLUME UP ########################################################################################################

    def volume_up(self, group_command=False):
        """
        volume + 2 is the default sonos speaker behaviour, if the volume-up button was pressed
        :param group_command: if True, the volume for all group members is increased by 2
        """
        self._volume_up()
        if group_command:
            for speaker in self.zone_members:
                speaker._volume_up()

    def _volume_up(self):
        vol = self.volume
        vol += 2
        if vol > 100:
            vol = 100
        self.set_volume(vol, trigger_action=True)

    # VOLUME DOWN ######################################################################################################

    def volume_down(self, group_command=False):

        """
        volume - 2 is the default sonos speaker behaviour, if the volume-down button was pressed
        :param group_command: if True, the volume for all group members is decreased by 2
        """

        self._volume_down()
        if group_command:
            for speaker in self.zone_members:
                speaker._volume_down()

    def _volume_down(self):
        vol = self.volume
        vol -= 2
        if vol < 0:
            vol = 0
        self.set_volume(vol, trigger_action=True)

    # MAX VOLUME #######################################################################################################

    def get_maxvolume(self):

        """
        Getter function for property max_volume.
        :return: None
        """

        return self._max_volume

    def set_maxvolume(self, value, group_command=False):

        """
        Setter function for property max_volume.
        :param value: max_volume as an integer between -1 and 100. If value == -1, no maximum value is assumed.
        :param group_command: If True, the maximum volume for all group members is set.
        """

        self._set_maxvolume(value)
        if group_command:
            for speaker in self.zone_members:
                speaker._set_maxvolume(value)

    def _set_maxvolume(self, value):

        m_volume = int(value)
        if m_volume is not -1:
            self._max_volume = m_volume
            if utils.check_volume_range(self._max_volume):
                if self.volume > self._max_volume:
                    self.set_volume(self._max_volume, trigger_action=True)
        else:
            self._max_volume = m_volume
        self.dirty_property('max_volume')

    # UID ##############################################################################################################

    @property
    def uid(self):
        return self._uid.lower()

    # MUTE #############################################################################################################

    def get_mute(self):
        return self._mute

    def set_mute(self, value, trigger_action=False, group_command=False):
        """
        By default, mute is not a group command, but the sonos app handles the mute command as a group command.
        :param value: mute value [0/1]
        :param trigger_action: triggers a soco action. Otherwise just a property setter
        :param group_command: Acts as a group command, all members in a group will be muted. False by default.
        """
        mute = int(value)

        if self._mute == mute:
            return
        if trigger_action:
            if group_command:
                for speaker in self._zone_members:
                    speaker.set_mute(mute, trigger_action=True, group_command=False)
            self.soco.mute = mute
        if self._mute == value:
            return
        self._mute = value
        self.dirty_property('mute')

    # TRACK_URI ########################################################################################################

    @property
    def track_uri(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_uri getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_uri
        return self._track_uri

    @track_uri.setter
    def track_uri(self, value):
        if self._track_uri == value:
            return
        self._track_uri = value
        # it seems, that Sonos not fire some events when cleaning a playlist
        # one event that is fired is track_uri
        # an empty track_uri signals an empty list

        if self._track_uri == "":
            self.clear_sonos_metadata()

        self.dirty_property('track_uri')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                if self.track_uri == "":
                    speaker.clear_sonos_metadata()
                speaker.dirty_property('track_uri')

    def clear_sonos_metadata(self):
        self.track_album_art = ""
        self.track_artist = ""
        self.track_title = ""
        self.playlist_position = 0
        self.playlist_total_tracks = 0
        self.track_album = ""
        self.radio_show = ""
        self.radio_station = ""
        self.track_duration = ""

    # TRACK DURATION ###################################################################################################

    @property
    def track_duration(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_duration getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_duration
        if not self._track_duration:
            return "00:00:00"
        return self._track_duration

    @track_duration.setter
    def track_duration(self, value):
        if self._track_duration == value:
            return
        self.dirty_property('track_duration')
        self._track_duration = value

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_duration')

    # TRACK POSITION ###################################################################################################

    def get_trackposition(self, force_refresh=False):
        """
        Gets the current track position.
        :param force_refresh:
        :return: You have to poll this value manually. There is no sonos event for a track position change.
        """
        if not self.is_coordinator:
            logger.debug("forwarding track_position getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.get_trackposition(force_refresh=force_refresh)

        if force_refresh:
            track_info = self.soco.get_current_track_info()
            self.track_position = track_info['position']
        if not self._track_position:
            return "00:00:00"
        return self._track_position

    def set_trackposition(self, value, trigger_action=False):
        """
        Sets the track position.
        :param  value: track position to set (format: HH:MM:ss)
        :param  trigger_action: If True, the value is passed to SoCo and triggers a seek command. If False, the
                behavior of this function is more or less like a property
        :rtype : None
        """
        if trigger_action:
            if not self.is_coordinator:
                logger.debug("forwarding trackposition setter to coordinator with uid {uid}".
                             format(uid=self.zone_coordinator.uid))
                self.zone_coordinator.set_trackposition(value, trigger_action)
            else:
                self.soco.seek(value)
        if self._track_position == value:
            return
        self._track_position = value
        self.dirty_property('track_position')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_position')

    # PLAYLIST POSITION ################################################################################################

    @property
    def playlist_position(self):
        if not self.is_coordinator:
            logger.debug("forwarding playlist_position getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.playlist_position

        return self._playlist_position

    @playlist_position.setter
    def playlist_position(self, value):
        if self._playlist_position == value:
            return
        self._playlist_position = value
        self.dirty_property('playlist_position')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('playlist_position')

    # PLAYLIST TOTAL NUMBER TRACKS #####################################################################################

    @property
    def playlist_total_tracks(self):
        if not self.is_coordinator:
            logger.debug("forwarding playlist_position getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.playlist_total_tracks
        return self._playlist_total_tracks

    @playlist_total_tracks.setter
    def playlist_total_tracks(self, value):
        if self._playlist_total_tracks == value:
            return
        self._playlist_total_tracks = value
        self.dirty_property('playlist_total_tracks')
        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('playlist_total_tracks')

    # STREAMTYPE #######################################################################################################

    @property
    def streamtype(self):
        if not self.is_coordinator:
            logger.debug("forwarding streamtype getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.streamtype
        return self._streamtype

    @streamtype.setter
    def streamtype(self, value):
        if self._streamtype == value:
            return
        self._streamtype = value
        self.dirty_property('streamtype')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('streamtype')

    # STOP #############################################################################################################

    def get_stop(self):
        if not self.is_coordinator:
            logger.debug("forwarding stop getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.stop
        return self._stop

    def set_stop(self, value, trigger_action=False):
        stop = int(value)
        if self._stop == stop:
            return
        if trigger_action:
            if not self.is_coordinator:
                logger.debug("forwarding stop setter to coordinator with uid {uid}".
                             format(uid=self.zone_coordinator.uid))
                self.zone_coordinator.set_stop(stop, trigger_action=True)
            else:
                if stop:
                    self.soco.stop()
                else:
                    self.soco.play()

        if self._stop == stop:
            return

        self._stop = stop
        self._play = int(not self._stop)
        self._pause = 0
        self.dirty_property('stop', 'play', 'pause')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('pause', 'play', 'stop')

    # PLAY #############################################################################################################

    def get_play(self):
        if not self.is_coordinator:
            logger.debug("forwarding play getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.play
        return self._play

    def set_play(self, value, trigger_action=False):
        play = int(value)
        if self._play == play:
            return
        if trigger_action:
            if not self.is_coordinator:
                logger.debug("forwarding play setter to coordinator with uid {uid}".
                             format(uid=self.zone_coordinator.uid))
                self.zone_coordinator.set_play(play, trigger_action=True)
            else:
                if play:
                    self.soco.play()
                else:
                    self.soco.pause()

        if self._play == play:
            return

        self._play = play
        self._pause = 0
        self._stop = int(not self._play)
        self.dirty_property('pause', 'play', 'stop')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('pause', 'play', 'stop')

    # PAUSE ############################################################################################################

    def get_pause(self):
        if not self.is_coordinator:
            logger.debug("forwarding pause getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.pause
        return self._pause

    def set_pause(self, value, trigger_action=False):
        pause = int(value)
        if self._pause == pause:
            return
        if trigger_action:
            if not self.is_coordinator:
                logger.debug("forwarding pause setter to coordinator with uid {uid}".
                             format(uid=self.zone_coordinator.uid))
                self.zone_coordinator.set_pause(pause, trigger_action=True)
            else:
                if pause:
                    self.soco.pause()
                else:
                    self.soco.play()

        if self._pause == pause:
            return

        self._pause = pause
        self._play = int(not self._pause)
        self._stop = 0
        self.dirty_property('pause', 'play', 'stop')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('pause', 'play', 'stop')

    # TRACK ALBUM ######################################################################################################

    @property
    def track_album(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_album getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_album
        return self._track_album

    @track_album.setter
    def track_album(self, value):
        if self._track_album == value:
            return
        self._track_album = value
        self.dirty_property('track_album')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_album')

    # TRANSPORT ACTIONS ################################################################################################

    @property
    def transport_actions(self):
        if not self.is_coordinator:
            logger.debug("forwarding transport_actions getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.transport_actions
        return self._transport_actions

    @transport_actions.setter
    def transport_actions(self, value):
        if self._transport_actions == value:
            return
        self._transport_actions = value
        self.dirty_property('transport_actions')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('transport_actions')

    # RADIO STATION ####################################################################################################

    @property
    def radio_station(self):
        if not self.is_coordinator:
            logger.debug("forwarding radio_station getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.radio_station
        return self._radio_station

    @radio_station.setter
    def radio_station(self, value):
        if self._radio_station == value:
            return
        self._radio_station = value
        self.dirty_property('radio_station')

        # dirty properties for all zone members, if coordinator
        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('radio_station')

    # RADIO SHOW #######################################################################################################

    @property
    def radio_show(self):
        if not self.is_coordinator:
            logger.debug("forwarding radio_show getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.radio_show
        return self._radio_show

    @radio_show.setter
    def radio_show(self, value):
        if self._radio_show == value:
            return
        self._radio_show = value
        self.dirty_property('radio_show')

        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('radio_show')

    # TRACK ALBUM ART ##################################################################################################

    @property
    def track_album_art(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_album_art getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_album_art
        return self._track_album_art

    @track_album_art.setter
    def track_album_art(self, value):
        if self._track_album_art == value:
            return
        self._track_album_art = value
        self.dirty_property('track_album_art')

        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_album_art')

    # TRACK TITLE ######################################################################################################

    @property
    def track_title(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_title getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_title
        if not self._track_title:
            return ''
        return self._track_title

    @track_title.setter
    def track_title(self, value):
        if self._track_title == value:
            return
        self._track_title = value
        self.dirty_property('track_title')

        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_title')

    # TRACK ARTIST #####################################################################################################

    @property
    def track_artist(self):
        if not self.is_coordinator:
            logger.debug("forwarding track_artist getter to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            return self.zone_coordinator.track_artist
        if not self._track_artist:
            return ''
        return self._track_artist

    @track_artist.setter
    def track_artist(self, value):
        if self._track_artist == value:
            return
        self._track_artist = value
        self.dirty_property('track_artist')

        if self.is_coordinator:
            for speaker in self._zone_members:
                speaker.dirty_property('track_artist')

    # NEXT #############################################################################################################

    def next(self):
        if not self.is_coordinator:
            logger.debug("forwarding next command to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            self.zone_coordinator.next()
        else:
            self.soco.next()

    # PREVIOUS #########################################################################################################

    def previous(self):
        if not self.is_coordinator:
            logger.debug("forwarding previous command to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            self.zone_coordinator.previous()
        else:
            self.soco.previous()

    # NIGHTMODE ########################################################################################################

    def get_nightmode(self):
        if self._nightmode is None:
            return 0
        return int(self._nightmode)

    def set_nightmode(self, value, trigger_action=False):
        night_mode = 0
        try:
            if bool(value):
                night_mode = 1
            else:
                night_mode = 0
        except:
            pass
        if self._nightmode == night_mode:
            return

        if trigger_action:
            self.soco.night_mode = night_mode

        self._nightmode = night_mode
        self.dirty_property('nightmode')

    # PARTYMODE ########################################################################################################

    def partymode(self):

        """
        Joins all speakers to the current speaker group.
        :rtype : None
        """

        self.soco.partymode()

    # JOIN #############################################################################################################

    def join(self, join_uid):

        """
        Joins a Sonos speaker to another speaker / group.
        :param join_uid: A uid of any speaker of the group, the speaker has to join.
        :raise Exception: No master speaker was found
        """

        try:
            if not sonos_speakers[join_uid].is_coordinator:
                speaker = [speaker for speaker in sonos_speakers[join_uid].zone_members if
                           speaker.is_coordinator is True][0]
            else:
                speaker = sonos_speakers[join_uid]
            self.soco.join(speaker.soco)
            sec_to_wait = 3
            logger.debug("Waiting {sleep} seconds after join ...".format(sleep=sec_to_wait))
            time.sleep(sec_to_wait)
        except Exception:
            raise Exception('No master speaker found for uid \'{uid}\'!'.format(uid=join_uid))

    # UNJOIN ###########################################################################################################

    def unjoin(self, play=False):

        """
        Unjoins the current speaker from a group.
        """
        self.soco.unjoin()
        sec_to_wait = 3
        logger.debug("Waiting {sleep} seconds after unjoin ...".format(sleep=sec_to_wait))
        time.sleep(sec_to_wait)
        self.set_play(play, trigger_action=True)

    # CURRENT STATE ####################################################################################################

    def current_state(self, group_command=False):

        """
        Refreshs all values for the current speaker. All values will be send to the connected clients.
        :param group_command: Refreshs the status for all additional zone members
        """

        self.dirty_all()
        if group_command:
            for speaker in self._zone_members:
                speaker.current_state(group_command=False)

    # WIFI STATE #######################################################################################################

    def get_wifi_state(self, force_refresh=False):
        """
        Gets the current wifi state.
        :param force_refresh:
        :return: You have to poll this value manually. There is no sonos event for a wifi state change.
        """

        if force_refresh:
            url = "http://{ip}:1400/status/ifconfig".format(ip=self.ip)
            wifi_request = requests.get(url, timeout=5)
            if wifi_request.status_code is not 200:
                raise Exception("Could not retrieve wifi state from speaker with uid '{uid}'".format(uid=self.uid))

            if 'ath0' in wifi_request.text:
                self._wifi_state = 1
            else:
                self._wifi_state = 0

        return self._wifi_state

    def set_wifi_state(self, value, persistent=False, trigger_action=False):
        """
        Sets the wifi state
        :param  value: wifi state: on, off, persistent-off
        :param  trigger_action: If True, the value is passed to the sonos speaker to change the wifi state. If False,
                the behavior of this function is more or less like a property.
        :rtype : None
        """

        if isinstance(value, str):
            value = value.lower()

        if value in [0, 'off', False, '0']:
            named_value = 'off'
            value = 0

        else:
            # default should be wifi on, this is the default sonos behaviour
            named_value = 'on'
            value = 1

        if trigger_action:
            if persistent and not value:
                persistent = "persist-"
            else:
                persistent = ''

            url = "http://{ip}:1400/wifictrl?wifi={persistent}{named_value}".format(ip=self.ip, persistent=persistent,
                                                                                    named_value=named_value)

            # after disabling / enabling  the wifi, sometimes the event subscriptions act oddly
            # we'll unsubscribe an re-subscribe the events

            logger.debug("Unsubscribing events ... ")
            self.event_unsubscribe()

            response = requests.get(url, timeout=5)

            if response.status_code is not 200:
                raise Exception("Could not set wifi state for speaker with uid '{uid}'.\nError: {err}".format(
                    uid=self.uid, err=response.text)
                )
            logger.debug("Wifi state set for speker with uid '{uid}'.".format(uid=self.uid))

            # re-registering
            threading.Timer(15, self.event_subscription).start()

        if self._wifi_state == value:
            return
        self._wifi_state = value
        self.dirty_property('wifi_state')

    # LOAD SONOS PLAYLIST ##############################################################################################

    def load_sonos_playlist(self, sonos_playlist_name, play_after_insert=False, clear_queue=False):
        try:
            if not sonos_playlist_name:
                raise Exception("A valid playlist name must be provided.")
            playlist = self.soco.get_sonos_playlist_by_attr('title', sonos_playlist_name)
            if playlist:
                if clear_queue:
                    self.soco.clear_queue()
                self.soco.add_to_queue(playlist)
                self.soco.play_from_queue(0, play_after_insert)
        except Exception:
            raise Exception("No Sonos playlist found with title '{title}'.".format(title=sonos_playlist_name))

    # Clear Queue ######################################################################################################

    def clear_queue(self):
        """
        Removes all tracks from the queue.
        :rtype : object
        """
        self.soco.clear_queue()

    # Play TuneIn Radio ################################################################################################

    def play_tunein(self, station_name):

        """
        Plays a tunein radio uri
        :param station_name: the give name is searched in all TuneIn music stations. The first match is chosen.
        """

        if not self.is_coordinator:
            logger.debug("forwarding play_tunein_radio command to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            self.zone_coordinator.play_tunein_url(station_name)
        else:

            service = MusicService('TuneIn')
            result = service.search(category='stations', term=station_name)
            if not result:
                logger.warning("No radio station found for search string '{term}'.".format(term=station_name))
                return

            item = result[0]
            meta = to_didl_string(item)
            id = item.metadata['id']
            account = service.account

            uri = "x-sonosapi-stream:{0}?sid={1}&sn={2}".format(id, service.service_id, account.serial_number)

            self.soco.avTransport.SetAVTransportURI([('InstanceID', 0),
                                                     ('CurrentURI', uri), ('CurrentURIMetaData', meta)])
            self.soco.play()

    # Sonos Playlists ##################################################################################################

    @property
    def sonos_playlists(self):
        """
        Returns all Sonos playlist as string, delimited by ','
        :return:
        """
        playlists = ','.join(str(playlist.title) for playlist in self.soco.get_sonos_playlists())
        if not playlists:
            playlists = ''
        return playlists

    def dirty_music_metadata(self):

        """
        Small helper function to make the music metadata properties 'dirty' after a speaker was joined or un-joined
        to or from a group.
        """

        self.dirty_property(
            'track_title',
            'track_position',
            'track_album_art',
            'track_artist',
            'track_uri',
            'track_duration',
            'track_album',
            'transport_actions',
            'stop',
            'play',
            'pause',
            'mute',
            'radio_station',
            'radio_show',
            'playlist_position',
            'playlist_total_tracks',
            'streamtype',
            'playmode',
            'zone_icon',
            'zone_name',
            'playmode',
        )

    def dirty_all(self):

        self.dirty_music_metadata()

        self.dirty_property(
            'nightmode',
            'sonos_playlists',
            'household_id',
            'display_version',
            'ip',
            'mac_address',
            'software_version',
            'hardware_version',
            'serial_number',
            'led',
            'volume',
            'max_volume',
            'mute',
            'additional_zone_members',
            'status',
            'model',
            'model_number',
            'bass',
            'treble',
            'loudness',
            'alarms',
            'is_coordinator',
            'wifi_state',
            'balance',
        )

    @property
    def alarms(self):
        return self._alarms

    @alarms.setter
    def alarms(self, value):
        if value != self._alarms:
            self._alarms = value
            self.dirty_property('alarms')

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        if value == self._status:
            return

        self._status = value

        if self._status == 0:
            self._wifi_state = 0
            self._streamtype = ''
            self._volume = 0
            self._bass = 0
            self._treble = 0
            self._loudness = 0
            self._additional_zone_members = ''
            self._mute = False
            self._led = True
            self._stop = False
            self._play = False
            self._pause = False
            self._track_title = ''
            self._track_artist = ''
            self._transport_actions = ''
            self._track_duration = "00:00:00"
            self._track_position = "00:00:00"
            self._playlist_position = 0
            self._playlist_total_tracks = 0
            self._track_uri = ''
            self._track_album_art = ''
            self._radio_show = ''
            self._radio_station = ''
            self._max_volume = -1
            self._zone_name = ''
            self._zone_coordinator = self
            self._zone_icon = ''
            self._playmode = ''
            self._alarms = ''

        self.dirty_property('status')

    def play_uri(self, uri):

        """
        Plays a song from a given uri
        :param uri: uri to be played
        :return: True, if the song is played.
        """
        if not self.is_coordinator:
            logger.debug("forwarding play_uri command to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            self.zone_coordinator.play_uri(uri)
        else:
            return self.soco.play_uri(uri)

    def play_snippet(self, uri, volume=-1, group_command=False, fade_in=False):

        """
        Plays a audio snippet. This will pause the current audio track , plays the snippet and after that, the previous
        track will be continued.
        :param fade_in: Fade-In after the snippet was played. Default: false
        :param uri: uri to be played
        :param volume: Snippet volume [-1-100]. After the snippet was played, the previous/original volume is set. If
        volume is '-1', the current volume is used. Default: -1
        :param group_command: Only affects the volume. If True, the snippet volume is set to all zone members. Default:
        False
        :raise err:
        """

        if not self.is_coordinator:
            logger.debug("forwarding play_snippet command to coordinator with uid {uid}".
                         format(uid=self.zone_coordinator.uid))
            self._zone_coordinator.play_snippet(uri, volume, group_command=group_command)
        else:
            with self._snippet_queue_lock:
                try:

                    volumes = {}
                    # save all volumes from zone_member
                    for member in self.zone_members:
                        volumes[member] = member.volume

                    # Take a snapshot of the current sonos device state, we will want
                    # to roll back to this when we are done
                    logger.debug("Speech: Taking snapshot")

                    # was GoogleTTS the last track? do not snapshot
                    last_station = self.radio_station
                    if last_station.lower() != "google tts":
                        snap = Snapshot(self.soco)
                        snap.snapshot()

                    # Get the URI and play it
                    logger.debug("Speech: Playing URI %s" % uri)

                    self.set_stop(1, trigger_action=True)

                    if volume == -1:
                        volume = self.volume

                    if self.volume != volume:
                        self.set_volume(volume, trigger_action=True, group_command=group_command)

                    time.sleep(0.5)
                    self.soco.play_uri(uri, title="Google TTS")
                    self.stop_tts.wait(timeout=120)  # wait max 120sec
                    self.stop_tts.clear()
                    time.sleep(0.5)

                    # testing play_snippet stop for stereo pair
                    for speaker in self._zone_members:
                        try:
                            logger.debug("tts force stop trigger for speaker {speaker}".format(speaker=speaker.uid))
                            res = speaker.soco.stop()
                            logger.debug("{uid}: stop result = {res}".format(uid=speaker.soco.uid, res=res))
                            speaker.stop_tts.clear()
                        except Exception as err:
                            logger.debug("{uid} error: {err}".format(uid=speaker.soco.uid, err=err))

                    logger.debug("Speech: Stopping speech")
                    # Stop the stream playing
                    self.soco.stop()
                    logger.debug("Speech: Restoring snapshot")

                    # Restore the Sonos device back to it's previous state
                    if last_station.lower() != "google tts":
                        snap.restore()
                    else:
                        self.radio_station = ""

                    for member in self.zone_members:
                        if member in volumes:
                            if fade_in:
                                vol_to_ramp = volumes[member]
                                member.soco.volume = 0
                                member.soco.renderingControl.RampToVolume(
                                    [('InstanceID', 0), ('Channel', 'Master'),
                                     ('RampType', 'SLEEP_TIMER_RAMP_TYPE'),
                                     ('DesiredVolume', vol_to_ramp),
                                     ('ResetVolumeAfter', False), ('ProgramURI', '')])
                            else:
                                member.set_volume(volumes[member], trigger_action=True, group_command=False)

                except Exception as err:
                    print(err)

    def play_tts(self, tts, volume, language='en', group_command=False, fade_in=False, force_stream_mode=False):
        # we do not need any code here to get the zone coordinator.
        # The play_snippet function does the necessary work.

        local_mode = SonosSpeaker.tts_local_mode
        # override if stream is set to True
        if force_stream_mode:
            local_mode = False

        # default mode: give the prepared url directly to our loudspeaker
        if not local_mode:
            url = utils.stream_google_tts(tts, language)
        else:
            filename = utils.save_google_tts(SonosSpeaker.local_folder, tts, language, SonosSpeaker.quota)

            if SonosSpeaker.local_folder.endswith('/'):
                SonosSpeaker.local_folder = SonosSpeaker.local_folder[:-1]
            url = '{}/{}'.format(SonosSpeaker.local_url, filename)

        self.play_snippet(url, volume, group_command, fade_in)

    def set_add_to_queue(self, uri):
        self.soco.add_to_queue(uri)

    def send(self):
        self._send()
        '''
        we need to trigger all zone members, because slave members never trigger events
        '''
        for speaker in self._zone_members:
            if len(speaker._dirty_properties) > 0:
                speaker._send()

    def _send(self):
        dirty_values = {}
        for prop in self._dirty_properties:
            value = getattr(self, prop)
            dirty_values[prop] = value
        if len(dirty_values) == 0:
            return

        '''
        always add the uid
        '''
        dirty_values['uid'] = self.uid

        data = json.dumps(self, default=lambda o: dirty_values, sort_keys=True, ensure_ascii=False, indent=4,
                          separators=(',', ': '))
        udp_broker.UdpBroker.udp_send(data)

        '''
        empty list
        '''
        del self._dirty_properties[:]

    def event_unsubscribe(self):

        """
        Unsubcribes the Broker from the event queue.
        """

        try:
            if self.sub_zone_group is not None:
                self.sub_zone_group.unsubscribe()
            if self.sub_alarm is not None:
                self.sub_alarm.unsubscribe()
            if self.sub_system_properties is not None:
                self.sub_system_properties.unsubscribe()
            if self.sub_av_transport is not None:
                self.sub_av_transport.unsubscribe()
            if self.sub_rendering_control is not None:
                self.sub_rendering_control.unsubscribe()
        except ConnectionError:
            logger.warning("Speaker offline. Could not un-subscribe.")
        except Exception as err:
            logger.exception(err)
        finally:
            self._sub_zone_group = None
            self._sub_alarm = None
            self._sub_system_prop = None
            self._sub_av_transport = None
            self._sub_rendering_control = None

    def event_subscription(self):

        """
        Subscribes the Broker to all necessary Sonos speaker events
        :param event_queue:
        """

        try:
            if self.sub_zone_group is not None:
                if not self.sub_zone_group.time_left:
                    try:
                        self._sub_zone_group.unsubscribe()
                    except Exception as err:
                        logger.warning(err)
                    self._sub_zone_group = None
            if self.sub_zone_group is None:
                logger.debug('renewing topology event for {uid}'.format(uid=self.uid))
                try:

                    self._sub_zone_group = self.soco.zoneGroupTopology.subscribe(definitions.SUBSCRIPTION_TIMEOUT,
                                                                                 True, SonosSpeaker.event_queue)
                except Exception as err:
                    logger.warning(err)
                    pass

            if self.sub_av_transport is not None:
                if not self.sub_av_transport.time_left:
                    try:
                        self.sub_av_transport.unsubscribe()
                    except Exception as err:
                        logger.warning(err)
                    self._sub_av_transport = None
            if self.sub_av_transport is None:
                logger.debug('renewing av-transport event for {uid}'.format(uid=self.uid))
                try:
                    self._sub_av_transport = self.soco.avTransport.subscribe(definitions.SUBSCRIPTION_TIMEOUT,
                                                                             True, SonosSpeaker.event_queue)
                except Exception as err:
                    logger.warning(err)
                    pass

            if self.sub_rendering_control is not None:
                if not self.sub_rendering_control.time_left:
                    try:
                        self.sub_rendering_control.unsubscribe()
                    except Exception as err:
                        logger.warning(err)
                    self._sub_rendering_control = None
            if self.sub_rendering_control is None:
                logger.debug('renewing rendering event for {uid}'.format(uid=self.uid))
                try:
                    self._sub_rendering_control = self.soco.renderingControl.subscribe(definitions.SUBSCRIPTION_TIMEOUT,
                                                                                       True, SonosSpeaker.event_queue)
                except Exception as err:
                    logger.warning(err)
                    pass

            if self.sub_alarm is not None:
                if not self.sub_alarm.time_left:
                    try:
                        self.sub_alarm.unsubscribe()
                    except Exception as err:
                        logger.warning(err)
                    self._sub_alarm = None
            if self.sub_alarm is None:
                logger.debug('renewing alarm event for {uid}'.format(uid=self.uid))
                try:
                    self._sub_alarm = self.soco.alarmClock.subscribe(definitions.SUBSCRIPTION_TIMEOUT, True,
                                                                     SonosSpeaker.event_queue)
                except Exception as err:
                    logger.warning(err)
                    pass

        except Exception as err:
            logger.exception(err)

    def get_alarms(self):
        """
        Gets all alarms for the speaker
        :return:
        """
        try:
            values = get_alarms(self.soco)
        except:
            return {}
        alarm_dict = {}
        for alarm in values:
            if alarm.zone.uid.lower() != self.uid.lower():
                continue
            dict = SonosSpeaker.alarm_to_dict(alarm)
            alarm_dict[alarm._alarm_id] = dict
        self.alarms = alarm_dict

    @staticmethod
    def alarm_to_dict(alarm):
        return {
            'Enabled': alarm.enabled,
            'Duration': str(alarm.duration),
            'PlayMode': alarm.play_mode,
            'Volume': alarm.volume,
            'Recurrence': alarm.recurrence,
            'StartTime': str(alarm.start_time),
            'IncludedLinkZones': alarm.include_linked_zones
            # 'ProgramUri': alarm.program_uri,
            # 'ProgramMetadata': alarm.program_metadata,
            # 'Uid': alarm.zone.uid
        }

    def dirty_property(self, *args):
        for arg in args:
            if arg not in self._dirty_properties:
                self._dirty_properties.append(arg)

    def set_zone_coordinator(self):
        if self.soco.group is None:
            return
        soco = next(member for member in self.soco.group.members if member.is_coordinator is True)
        if not soco:
            '''
            current instance is the coordinator
            '''
            self._zone_coordinator = None

        self._zone_coordinator = sonos_speakers[soco.uid.lower()]
        self.dirty_property('is_coordinator')

    def set_group_members(self):
        del self.zone_members[:]

        if not self.soco.group:
            return

        for member in self.soco.group.members:
            member_uid = member.uid.lower()
            if member_uid != self.uid:
                self.zone_members.append(sonos_speakers[member_uid])

    def terminate(self):
        self.event_unsubscribe()
        self.zone_members[:] = []
        self._zone_members.unregister_callback(self.zone_member_changed)
        self._zone_members = None
        del self._soco

    led = property(get_led, set_led)
    bass = property(get_bass, set_bass)
    treble = property(get_treble, set_treble)
    loudness = property(get_loudness, set_loudness)
    volume = property(get_volume, set_volume)
    balance = property(get_balance, set_balance)
    mute = property(get_mute, set_mute)
    playmode = property(get_playmode, set_playmode)
    stop = property(get_stop, set_stop)
    play = property(get_play, set_play)
    pause = property(get_pause, set_pause)
    max_volume = property(get_maxvolume, set_maxvolume)
    track_position = property(get_trackposition, set_trackposition)
    wifi_state = property(get_wifi_state, set_wifi_state)
    nightmode = property(get_nightmode, set_nightmode)
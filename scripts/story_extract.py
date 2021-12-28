import enum
import json
import itertools
import sqlite3
import UnityPy
from dataclasses import dataclass
from pathlib import Path
from typing import List
from UnityPy.enums import ClassIDType
from collections import defaultdict

from utils import get_master_conn, get_storage_folder, get_logger, get_girls_dict, get_support_to_char_map

logger = get_logger(__name__)

LIMIT = 200
SKIP_EXISTING = True

DATA_ROOT = get_storage_folder('data')
STORY_ROOT = get_storage_folder('story')
MAIN_STORY_TABLE = 'main_story_data'
EVENT_STORY_TABLE = 'story_event_story_data'
CHARACTER_STORY_TABLE = 'chara_story_data'
SINGLE_MODE_STORY_TABLE = 'single_mode_story_data'
MAIN_STORY_SEG_MAX = 5
MAIN_STORY_SEG_COLUMNS = ', '.join([
    column
    for i in range(1, MAIN_STORY_SEG_MAX + 1) for column in [f'"story_type_{i}"', f'"story_id_{i}"']
])


class SegmentKind(enum.Enum):
    TEXT = 1
    LIVE = 2
    SPECIAL = 3
    RACE = 4

    def __str__(self):
        if self is self.TEXT:
            return 'text'
        if self is self.LIVE:
            return 'live'
        if self is self.SPECIAL:
            return 'special'
        if self is self.RACE:
            return 'race'


@dataclass
class LineData:
    name: str
    text: str


@dataclass
class SegmentData:
    id: int
    order: int
    kind: SegmentKind

    def get_lines(self) -> List[LineData]:
        return fetch_segment_lines(self)


@dataclass
class EpisodeData:
    id: int
    segments: List[SegmentData]


@dataclass
class StoryData:
    id: int
    kind: str
    episodes: List[EpisodeData]


def story_extract():
    save_stories(fetch_main_story_data())
    save_stories(fetch_event_story_data())
    save_stories(fetch_character_story_data())
    save_stories(fetch_single_mode_story_data())


def save_stories(stories: List[StoryData]):
    for story in stories:
        save_story(story)


def save_story(story: StoryData):
    name = story.id
    if story.kind == 'chara':
        name = get_girls_dict()[story.id]
    if story.kind == 'single':
        split = name.split('/', 1)
        name = f'{get_girls_dict()[int(split[0])]}/{split[1]}'

    path = Path(STORY_ROOT, story.kind, f'{name}.txt')
    if SKIP_EXISTING and path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    data = format_story(story)
    with path.open('w', encoding='utf8') as f:
        f.write(data)


def format_story(story: StoryData):
    episodes_data = []
    for episode in story.episodes:
        segments_data = []
        for segment in episode.segments:
            lines_data = []
            try:
                lines = segment.get_lines()
            except Exception as e:
                logger.error(e, extra={'story': story})
                lines = []

            for line in lines:
                if line.text:
                    line_data = '{}{}\n'.format(('- {}:\n'.format(line.name) if line.name else ''), line.text.replace('\r\n', '\n'))
                    lines_data.append(line_data)

            segment_data = '\n'.join(lines_data)
            if story.kind == 'single':
                titles = get_single_story_segment_titles()
                title = titles[segment.id] if segment.id in titles else 'unknown'
                segments_data.append(f'Title: "{title}" ({segment.id})')
            segments_data.append(f'Segment {segment.order} ({str(segment.kind)}):\n{segment_data}')

        episode_data = '\n'.join(segments_data)
        episodes_data.append(f'Episode {episode.id}:\n{episode_data}')

    story_data = '\n'.join(episodes_data)
    return story_data


def fetch_segment_lines(segment: SegmentData):
    lines = []
    if segment.kind is SegmentKind.TEXT:
        story_id = str(segment.id).zfill(9)
        storyline_name = f'storytimeline_{story_id}'
        storytimeline_path = Path(DATA_ROOT, 'story/data', story_id[:2], story_id[2:6], storyline_name)
        env = UnityPy.load(storytimeline_path.as_posix())
        if not env.assets:
            raise FileNotFoundError(storytimeline_path)

        objects = {}
        timeline = None
        for obj in env.objects:
            if obj.type != ClassIDType.MonoBehaviour:
                continue

            if not timeline:
                obj_data = obj.read()
                if obj_data.name == storyline_name:
                    timeline = obj_data
                    continue

            objects[obj.path_id] = obj

        if not timeline:
            raise Exception("storytimeline exists, but it's timeline is missing")

        for block in timeline.type_tree['BlockList']:
            for clip in block['TextTrack']['ClipList']:
                # swap below if getting an error due to installed UnityPy version
                obj = objects[clip['m_PathID']]
                # obj = objects[clip.read().path_id]

                type_tree = obj.read().type_tree
                lines.append(LineData(type_tree['Name'], type_tree['Text']))

    return lines


def fetch_main_story_data():
    with get_master_conn() as master_conn:
        part_episodes = defaultdict(list)
        for part_id, episode_index, *segment_data in master_conn.execute(f'SELECT "part_id", "episode_index", {MAIN_STORY_SEG_COLUMNS} FROM "{MAIN_STORY_TABLE}"'):
            segments = [
                SegmentData(story_id, i, SegmentKind(story_type))
                for i, (story_type, story_id) in enumerate(zip(segment_data[::2], segment_data[1::2]), start=1) if story_type != 0
            ]

            part_episodes[part_id].append(EpisodeData(episode_index, segments))

        main_story_data = [StoryData(part_id, 'main', episodes) for part_id, episodes in part_episodes.items()]
        return main_story_data


def fetch_event_story_data():
    with get_master_conn() as master_conn:
        story_event_episodes = defaultdict(list)
        for event_id, episode_index, story_id  in master_conn.execute(f'SELECT "story_event_id", "episode_index_id", "story_id_1" FROM "{EVENT_STORY_TABLE}"'):
            segments = [SegmentData(story_id, 1, SegmentKind.TEXT)]
            story_event_episodes[event_id].append(EpisodeData(episode_index, segments))

        event_story_data = [StoryData(event_id, 'event', episodes) for event_id, episodes in story_event_episodes.items()]
        return event_story_data


def fetch_character_story_data():
    with get_master_conn() as master_conn:
        chara_episodes = defaultdict(list)
        for chara_id, episode_index, story_id  in master_conn.execute(f'SELECT "chara_id", "episode_index", "story_id" FROM "{CHARACTER_STORY_TABLE}"'):
            segments = [SegmentData(story_id, 1, SegmentKind.TEXT)]
            chara_episodes[chara_id].append(EpisodeData(episode_index, segments))

        character_story_data = [StoryData(chara_id, 'chara', episodes) for chara_id, episodes in chara_episodes.items()]
        return character_story_data


_single_story_segment_titles = None
def get_single_story_segment_titles():
    global _single_story_segment_titles
    if _single_story_segment_titles:
        return _single_story_segment_titles
    single_story_segment_titles = {}
    with get_master_conn() as master_conn:
        for index, text in master_conn.execute(f'SELECT "index", "text" FROM "text_data" WHERE "category" = 181'):
            single_story_segment_titles[index] = text
    _single_story_segment_titles = single_story_segment_titles
    return _single_story_segment_titles


def fetch_single_mode_story_data():
    with get_master_conn() as master_conn:
        single_mode_episodes = defaultdict(lambda: defaultdict(list))
        for story_id, card_id, card_chara_id, support_card_id, support_chara_id, show_progress_1, gallery_list_id\
                in master_conn.execute(f'SELECT "story_id", "card_id", "card_chara_id", "support_card_id", "support_chara_id", "show_progress_1", "gallery_list_id" FROM "{SINGLE_MODE_STORY_TABLE}"'):
            segments = [SegmentData(story_id, 1, SegmentKind.TEXT)]
            chara_id = card_chara_id

            # support cards do not have a card_chara_id set, so set that manually
            if support_card_id > 0:
                support_map = get_support_to_char_map()
                if support_card_id in support_map:
                    chara_id = support_map[support_card_id]
            
            if support_chara_id > 0:
                chara_id = support_chara_id

            # ignore anything that isnt associated to a character
            if chara_id > 0:
                # set file name and episode index depending on story type
                if card_id > 0:
                    desc = f'card_{card_id}'
                    indx = gallery_list_id
                elif support_card_id > 0:
                    desc = f'support_{support_card_id}'
                    indx = show_progress_1
                elif support_chara_id > 0:
                    desc = f'support_basic'
                    indx = 1
                else:
                    desc = 'basic'
                    indx = gallery_list_id
                single_mode_episodes[chara_id][desc].append(EpisodeData(indx, segments))

        def iter_episodes():
            for chara_id, items in single_mode_episodes.items():
                for card_id, episodes in items.items():
                    yield (chara_id, card_id, episodes)

        single_mode_story_data = [StoryData(
            f'{chara_id}/{card_id}', 'single', episodes) for (chara_id, card_id, episodes) in iter_episodes()]
        return single_mode_story_data


if __name__ == '__main__':
    story_extract()

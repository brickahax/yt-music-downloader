from enum import Enum
import sys
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TCON
from yt_dlp import YoutubeDL
import ytmusicapi
import os
import re
import json


class DownloaderMixin:
	class UrlType(Enum):
		Playlist = 1
		Video = 2
		Invalid = 3

	class OutputFormat(Enum):
		M4A = 1
		MP3 = 2

	def extract_youtube_id(self, url) -> tuple[str, UrlType]:
		# Regular expression pattern for extracting YouTube video ID (for youtube.com and youtu.be)
		video_pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|music\.youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})'
		
		# Regular expression pattern for extracting YouTube playlist ID (for youtube.com and music.youtube.com)
		playlist_pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/playlist\?list=|music\.youtube\.com/playlist\?list=)([a-zA-Z0-9_-]+)'
		
		# Check if the URL matches the video pattern
		video_match = re.search(video_pattern, url)
		if video_match:
			return (video_match.group(1), DownloaderMixin.UrlType.Video)  # Return video ID

		# Check if the URL matches the playlist pattern
		playlist_match = re.search(playlist_pattern, url)
		if playlist_match:
			return (playlist_match.group(1), DownloaderMixin.UrlType.Playlist)  # Return playlist ID

		return ('', DownloaderMixin.UrlType.Invalid)


	def get_video_url(self, video_id: str):
		return "https://www.youtube.com/watch?v=" + video_id
	

	'''Write video id to 'Genre' tag'''
	def set_yt_id_metadata(self, file_path: str, video_id: str, file_format: OutputFormat):
		if file_format == DownloaderMixin.OutputFormat.MP3:
			root, _ = os.path.splitext(file_path)
			file_path = root + '.mp3'
			audio_file = MP3(file_path, ID3=ID3)
			audio_file.tags.add(TCON(encoding=3, text=video_id))
		else:
			audio_file = MP4(file_path)
			audio_file.tags['\xa9gen'] = video_id
		audio_file.save()


	'''Get video id from 'Genre' tag'''
	def get_yt_id_metadata(self, file_path: str) -> str:
		_, file_format = os.path.splitext(file_path)
		if file_format == '.mp3':
			audio_file = MP3(file_path, ID3=ID3)
			tcon_data = audio_file.tags.get('TCON')
			if tcon_data:
				return tcon_data.text[0]
		else:
			audio_file = MP4(file_path)
			tag_data = audio_file.tags.get('\xa9gen')
			if tag_data:
				return tag_data[0]
		return None


	
	def download_songs(self, playlist, songs_limit: int, output_dir:str, output_format:OutputFormat):
		dest_dir = os.path.expanduser(output_dir)
		if not os.path.exists(dest_dir):
			os.makedirs(dest_dir)

		''' playlist may be specified in a few ways:
			1. playlist id
			2. return value of get_playlist() etc. (dict containing 'tracks' key with a list of dicts with 'videoId' keys)
			3. video id
		'''
		
		playlist_items = playlist

		if isinstance(playlist_items, (str, bytes)):
			# if playlist is a string, assume it is a playlist id and download the playlist
			playlist_items = self.get_playlist(playlist_items)
		elif hasattr(playlist_items, 'keys') and 'tracks' in playlist_items.keys():
			# if playlist is not string-like but is dict-like (or at least, has a keys() method ;) and
			# has a key 'tracks', assume it is a playlist data structure as returned by get_playlist()
			playlist_items = playlist_items['tracks']
		elif hasattr(playlist_items, 'keys') and 'videoDetails' in playlist_items.keys():
			# This is a single song
			playlist_items = [ playlist_items['videoDetails'] ]


		def init_existing_video_ids(dest_dir) -> set:
			'''Build set of existing video ids in the destination dir'''
			existing_ids: set = set()

			for dirpath, _, filenames in os.walk(dest_dir):
				for filename in filenames:
					# Get the full file path
					file_path = os.path.join(dirpath, filename)
					try:
						existing_file_yt_id = ytm.get_yt_id_metadata(file_path)
						if existing_file_yt_id is not None:
							existing_ids.add(existing_file_yt_id)
					except Exception as err:
						pass
			return existing_ids
		
		video_urls = []
		filtered_playlist_items = list(playlist_items)[:songs_limit]
		existing_video_ids: set = init_existing_video_ids(dest_dir)

		for listitem in filtered_playlist_items:
			if (not 'videoId' in listitem.keys()):
				raise KeyError("item in filtered_playlist_items does not have a videoId!")
			
			video_id = listitem['videoId']
			video_title = listitem['title']

			if (video_id in existing_video_ids):
				print(f'Skipping [{video_id}] - {video_title} - already exists')
				continue
			
			if (
				('duration_seconds' in listitem.keys() and listitem['duration_seconds'] > 130 * 60) or
				('lengthSeconds' in listitem.keys() and int(listitem['lengthSeconds']) > 130 * 60)
			): # Max 130min duration
				print(f'Skipping [{video_id}] - {video_title} - duration is too long')
				continue
			
			video_url = ytm.get_video_url(video_id)
			video_urls.append((video_url, video_id))

		file_format = 'mp3' if output_format == DownloaderMixin.OutputFormat.MP3 else 'm4a'
		
		ydl_opts = {
			'format': f'{file_format}/bestaudio/best',
			'postprocessors': [
				{ 'key': 'FFmpegExtractAudio', 'preferredcodec': file_format },
        		{ 'key': 'FFmpegMetadata' },
        		{ 'key': 'EmbedThumbnail' }
			],
			'writethumbnail': True,
			'outtmpl':  output_dir + '/%(uploader)s/%(title)s.%(ext)s'
		}

		for (video_url, video_id) in video_urls:
			try:
				with YoutubeDL(ydl_opts) as ydl:
					info_dict = ydl.extract_info(video_url, download=True)
					output_filename = ydl.prepare_filename(info_dict)
					ytm.set_yt_id_metadata(output_filename, video_id, output_format)
			except Exception as err:
				print(f"Exception caught while trying to download song {video_url}:  {err}")
		print('--- Finished ---------------------------------------------------------------------------')
	

	def download(self, url: str, limit: int, output_dir: str, output_format:OutputFormat):	
		if (url == 'likes'):
			ytm.download_songs(ytm.get_liked_songs(limit=limit), limit, output_dir, output_format)
			exit
		elif (url == 'history'):
			ytm.download_songs(ytm.get_history(), limit, output_dir, output_format)
			exit
		else:
			[id, type] = ytm.extract_youtube_id(url)

			if (type == DownloaderMixin.UrlType.Playlist):
				ytm.download_songs(ytm.get_playlist(id), limit, output_dir, output_format)
			elif (type == DownloaderMixin.UrlType.Video):
				ytm.download_songs(ytm.get_song(id), limit, output_dir, output_format)
			else:
				print("Couldn't parse url as youtube playlist or song. HINT: Use 'likes' or 'history' instead of a url to download from those playlists")


# Add the mixin to ytmusicapi class, creating our very own frankentype										
class YTMusic(ytmusicapi.YTMusic, DownloaderMixin):
	pass


def read_json_file(file_path) -> dict:
    # Open the file and load the JSON data
    with open(file_path, 'r') as file:
        data = json.load(file)  # Parse the JSON file into a Python dictionary
    return data


# A simple example you can run from the cli:										
if __name__ == "__main__":
	credentials = read_json_file('oauth-credentials.json')
	if ('client_id' not in credentials) or ('client_secret' not in credentials):
		print('Error: oauth-credentials.json file is not in the structure { "client_id": "-------", "client_secret": "-------" }')
		sys.exit(1)

	if not os.path.exists("oauth.json"):
		print('''
			Missing file "oauth.json"... see ytmusicapi.readthedocs.org for explanation of how to use an 
			authenticated watch page request in a signed-in browser and the browser devtools to set up oauth.json for
			ytmusicapi
		''')
		sys.exit(1)

	if len(sys.argv) < 2:
		print("Usage: python yt-music-downloader.py <playlist url | song url | 'likes' | 'history'> <OPTIONAL: output directory (default: ~Music)> <OPTIONAL: file format ['mp3' | 'm4a'] (default: 'm4a')> <OPTIONAL: songs limit int (default 500)>")
		sys.exit(1)

	url_to_download = sys.argv[1]

	output_dir = f'~{os.sep}Music'
	if (len(sys.argv) > 2):
		output_dir = sys.argv[2]
	
	output_format = DownloaderMixin.OutputFormat.M4A
	if (len(sys.argv) > 3):
		output_format = DownloaderMixin.OutputFormat.MP3 if sys.argv[3] == 'mp3' else DownloaderMixin.OutputFormat.M4A
	
	songs_limit = 500
	if (len(sys.argv) > 4):
		songs_limit = int(sys.argv[4])
	
	print(f"To download: {url_to_download}")
	print(f"Output directory: {output_dir}")
	print(f"Limit: {songs_limit}")

	ytm = YTMusic("oauth.json", oauth_credentials=ytmusicapi.OAuthCredentials(client_id=credentials['client_id'], client_secret=credentials['client_secret']))
	ytm.download(url_to_download, songs_limit, output_dir, output_format)

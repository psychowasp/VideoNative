import os
from kivy.utils import platform
import threading
import queue

if platform == "win":
    # Replace with the path of your ffmpeg dll bin directory. Only for windows.
    os.add_dll_directory(
        os.path.join(os.path.expanduser("~"), "Downloads", "ffmpeg", "bin")
    )  

from carbonkivy.app import CarbonApp
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import StringProperty, BooleanProperty, NumericProperty

import videonative

if platform not in ["android", "ios"]:
    Window.maximize()
Window.fullscreen = False

class VideoWidget(Image):
    filename = StringProperty()
    _running = BooleanProperty(False)
    _paused = BooleanProperty(False)
    current_pos = NumericProperty(0.0)
    duration = NumericProperty(0.0)
    current_pos_ratio = NumericProperty(0.0)
    buffering = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fps = 30.0
        self.frame_queue = queue.Queue(maxsize=3)
        self.read_thread = None
        self.decoder = None
        self._seek_lock = threading.Lock() # Prevents overlapping seek threads

    def on_filename(self, *args) -> None:
        if self.filename:
            self.open_video()

    def open_video(self, *args) -> None:
        self.buffering = True
        threading.Thread(target=self._background_load, daemon=True).start()

    def _background_load(self):
        """THIS RUNS IN THE BACKGROUND: Heavy network & FFmpeg initialization."""
        try:
            temp_decoder = videonative.MediaDecoder(self.filename)
            temp_decoder.start()

            first_frame = temp_decoder.get_next_frame()

            if first_frame is None:
                raise RuntimeError("Failed to read the first frame of the video.")

            # Convert to bytes here in the background to save UI thread time
            frame_bytes = first_frame.tobytes()
            height, width, _ = first_frame.shape

            Clock.schedule_once(
                lambda dt: self._on_video_loaded(temp_decoder, frame_bytes, width, height), 0
            )

        except Exception as e:
            print(f"Video Load Error: {e}")
            Clock.schedule_once(lambda dt: setattr(self, 'buffering', False), 0)

    def _on_video_loaded(self, loaded_decoder, frame_bytes, width_px, height_px) -> None:
        """THIS RUNS ON THE UI THREAD: Safely updates Kivy widgets."""
        self.decoder = loaded_decoder
        self.width_px = width_px
        self.height_px = height_px

        self.texture = Texture.create(
            size=(self.width_px, self.height_px), colorfmt="rgb"
        )
        self.texture.flip_vertical()

        self.texture.blit_buffer(
            frame_bytes, colorfmt="rgb", bufferfmt="ubyte"
        )
        self.canvas.ask_update()
        
        self.duration = self.decoder.get_duration()
        self.fps = self.decoder.get_fps()
        self.buffering = False
        self.play()

    def _reader_loop(self):
        """THIS RUNS IN THE BACKGROUND: Reads frames and serializes them."""
        while self._running and self.decoder:
            frame_arr = self.decoder.get_next_frame()

            if frame_arr is None:
                if self._running:
                    try:
                        self.frame_queue.put(None, timeout=0.1)
                    except queue.Full:
                        pass
                break

            # PERFORMANCE FIX: Call tobytes() here in the background thread.
            # This prevents the Kivy UI thread from doing heavy memory allocations.
            frame_bytes = frame_arr.tobytes()

            while self._running:
                try:
                    self.frame_queue.put(frame_bytes, timeout=0.1)
                    break
                except queue.Full:
                    continue

    def update_frame(self, dt) -> None:
        """UI THREAD: Lightest possible operation - just blit the pre-computed bytes."""
        try:
            frame_bytes = self.frame_queue.get_nowait()

            if self.buffering:
                self.buffering = False

            if frame_bytes is None:
                self.current_pos = self.duration
                self.current_pos_ratio = 1.0
                self.pause()
                return

            self.texture.blit_buffer(
                frame_bytes,
                size=(self.width_px, self.height_px),
                colorfmt="rgb",
                bufferfmt="ubyte",
            )
            self.canvas.ask_update()
            self.current_pos = self.decoder.get_position()
            
            if self.duration > 0:
                self.current_pos_ratio = self.current_pos / self.duration

        except queue.Empty:
            if self.decoder:
                self.buffering = self.decoder.is_buffering()

    def play(self, *args) -> None:
        if self._running or not self.decoder:
            return

        if self.duration > 0 and self.current_pos >= self.duration - 0.2:
            self.seek(-self.current_pos)

        self._running = True
        self._paused = False

        self.decoder.start()
        self.decoder.resume()

        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()

        # Update slightly faster than FPS to ensure we don't starve the queue
        Clock.schedule_interval(self.update_frame, 1.0 / (self.fps + 5))

    def stop(self, *args) -> None:
        self._running = False
        self._paused = False
        Clock.unschedule(self.update_frame)

        self._clear_queue()

        if self.decoder:
            self.decoder.stop()

        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1.0)
        self.read_thread = None

    def pause(self, *args) -> None:
        self._running = False
        self._paused = True

        if self.decoder:
            self.decoder.pause()

        Clock.unschedule(self.update_frame)
        self._clear_queue()

        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=0.2)
        self.read_thread = None

    def seek(self, offset: float | int) -> None:
        if not self.decoder:
            return

        # PERFORMANCE FIX: Don't block the UI thread waiting for the C++ seek.
        new_pos = max(0.0, min(self.duration, self.current_pos + offset))
        
        self.current_pos = new_pos
        if self.duration > 0:
            self.current_pos_ratio = self.current_pos / self.duration
            
        self.buffering = True # Show UI loading indicator
        was_running = self._running
        
        self._running = False
        Clock.unschedule(self.update_frame)
        if self.decoder:
            self.decoder.pause()

        # Fire and forget the background seek
        threading.Thread(target=self._background_seek, args=(new_pos, was_running), daemon=True).start()

    def _background_seek(self, new_pos, was_running):
        """THIS RUNS IN THE BACKGROUND: Allows C++ to block without freezing UI."""
        with self._seek_lock:
            self.decoder.seek(new_pos)
            self._clear_queue()
            
            # Re-sync with main thread to resume playback/updates
            Clock.schedule_once(lambda dt: self._post_seek_resume(was_running), 0)

    def _post_seek_resume(self, was_running):
        """UI THREAD: Resume state after background seek completes."""
        self.buffering = False
        if was_running:
            self.play()
        else:
            # If paused, pull exactly one frame to update the UI to the new position
            frame_arr = self.decoder.get_next_frame()
            if frame_arr is not None:
                self.texture.blit_buffer(
                    frame_arr.tobytes(), size=(self.width_px, self.height_px), colorfmt="rgb", bufferfmt="ubyte"
                )
                self.canvas.ask_update()

    def _clear_queue(self):
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    def set_volume(self, volume: float) -> None:
        if self.decoder:
            clamped_vol = max(0.0, min(1.0, volume))
            self.decoder.set_volume(clamped_vol)

    def restart(self, url: str, *args) -> None:
        self.buffering = True
        self.stop()
        self.decoder = None

        self.current_pos = 0.0
        self.current_pos_ratio = 0.0
        self.duration = 0.0

        if self.filename == url:
            self.open_video()
        else:
            self.filename = url


class VideoApp(CarbonApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Window.bind(on_key_down=self._on_key_down)

    def build(self):
        return Builder.load_file(os.path.join(os.path.dirname(__file__), "main.kv"))

    def _on_key_down(self, window, key, scancode, codepoint, modifiers):
        if key == 292: # F11
            self.maximize()
        return True

    def maximize(self, *args) -> None:
        Window.fullscreen = not Window.fullscreen

#if __name__ == "__main__":
def main():
    VideoApp().run()
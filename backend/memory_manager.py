import json

class MemoryManager:
    """
    Manages the context and memory for the hierarchical novel generation.
    Stores chapter summaries, character states, and major plot points.
    """
    def __init__(self):
        self.chapters = []  # List of {chapter_num, summary, key_events, characters_involved}
        self.characters = {} # Name -> {status, appearance, relationship_changes}
        self.world_facts = [] # List of established world facts

    def add_chapter_memory(self, chapter_num: int, summary: str, events: list, active_chars: list):
        """Adds a summary of a completed chapter to memory."""
        self.chapters.append({
            "chapter_num": chapter_num,
            "summary": summary,
            "events": events,
            "active_chars": active_chars
        })

    def update_character_state(self, name: str, state_update: dict):
        """Updates the state of a character."""
        if name not in self.characters:
            self.characters[name] = {}
        self.characters[name].update(state_update)

    def get_recent_context(self, k: int = 3) -> str:
        """Returns a text summary of the last k chapters."""
        recent = self.chapters[-k:]
        if not recent:
            return "No previous chapters."
        
        context = []
        for ch in recent:
            context.append(f"[Chapter {ch['chapter_num']}]\nSummary: {ch['summary']}\nKey Events: {', '.join(ch['events'])}")
        
        return "\n\n".join(context)

    def get_full_context_json(self) -> dict:
        """Returns the full memory state as a dict."""
        return {
            "chapters": self.chapters,
            "characters": self.characters,
            "world_facts": self.world_facts
        }

    def load_context_from_json(self, data: dict):
        """Loads memory state from a dict."""
        self.chapters = data.get("chapters", [])
        self.characters = data.get("characters", {})
        self.world_facts = data.get("world_facts", [])

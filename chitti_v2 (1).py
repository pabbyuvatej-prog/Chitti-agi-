#!/usr/bin/env python3
"""
CHITTI Cognitive Core V2.0
A compact, offline-first cognitive orchestration prototype.

Python: 3.9+
Dependencies: Python standard library only.
No arbitrary command execution is provided.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import sys
import textwrap
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "2.0.0"
APP_DIR = Path.home() / ".chitti_v2"
DB_PATH = APP_DIR / "chitti_memory.sqlite3"
MAX_CONTEXT_TURNS = 8
MAX_TEXT = 12000


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clip(value: str, limit: int = MAX_TEXT) -> str:
    value = str(value)
    return value if len(value) <= limit else value[:limit] + "\n[content clipped]"


def tokenize(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z0-9_'-]{3,}", text)]


class Store:
    """SQLite persistence for conversation, memory, feedback, knowledge and metrics."""

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            emotion TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT 'general',
            mkey TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.7,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, mkey)
        );
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user',
            confidence REAL NOT NULL DEFAULT 0.6,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL,
            rating INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            mode TEXT NOT NULL,
            chosen TEXT NOT NULL,
            scores_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            review TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        self.conn.commit()

    def add_turn(self, role: str, content: str, emotion: str = "") -> None:
        self.conn.execute(
            "INSERT INTO turns(role,content,emotion,created_at) VALUES(?,?,?,?)",
            (role, clip(content), emotion, now_iso()))
        self.conn.commit()

    def recent_turns(self, limit: int = MAX_CONTEXT_TURNS) -> List[Dict[str, str]]:
        rows = self.conn.execute(
            "SELECT role,content,emotion FROM turns ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def remember(self, key: str, value: str, category: str = "general",
                 confidence: float = 0.8) -> None:
        stamp = now_iso()
        self.conn.execute("""
        INSERT INTO memories(category,mkey,value,confidence,created_at,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(category,mkey) DO UPDATE SET
          value=excluded.value, confidence=excluded.confidence,
          updated_at=excluded.updated_at
        """, (category, key.strip(), clip(value, 4000),
              max(0.0, min(1.0, confidence)), stamp, stamp))
        self.conn.commit()

    def recall(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        words = tokenize(query)[:8]
        if not words:
            return []
        clauses, args = [], []
        for word in words:
            clauses.append("(mkey LIKE ? OR value LIKE ? OR category LIKE ?)")
            pattern = "%" + word + "%"
            args.extend([pattern, pattern, pattern])
        sql = ("SELECT id,category,mkey,value,confidence FROM memories WHERE "
               + " OR ".join(clauses) + " ORDER BY updated_at DESC LIMIT ?")
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def list_memories(self, limit: int = 30) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id,category,mkey,value,confidence,updated_at "
            "FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()]

    def forget(self, memory_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def forget_all(self) -> None:
        self.conn.execute("DELETE FROM memories")
        self.conn.commit()

    def add_knowledge(self, topic: str, content: str,
                      source: str = "user", confidence: float = 0.7) -> None:
        self.conn.execute(
            "INSERT INTO knowledge(topic,content,source,confidence,updated_at) "
            "VALUES(?,?,?,?,?)",
            (topic, clip(content, 5000), source, confidence, now_iso()))
        self.conn.commit()

    def search_knowledge(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        words = tokenize(query)[:6]
        if not words:
            return []
        clauses, args = [], []
        for word in words:
            clauses.append("(topic LIKE ? OR content LIKE ?)")
            pattern = "%" + word + "%"
            args.extend([pattern, pattern])
        args.append(limit)
        rows = self.conn.execute(
            "SELECT topic,content,source,confidence FROM knowledge WHERE "
            + " OR ".join(clauses) + " ORDER BY updated_at DESC LIMIT ?", args
        ).fetchall()
        return [dict(r) for r in rows]

    def add_feedback(self, target: str, rating: int, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO feedback(target,rating,note,created_at) VALUES(?,?,?,?)",
            (target, rating, clip(note, 2000), now_iso()))
        self.conn.commit()

    def feedback_summary(self) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, AVG(rating) AS avg FROM feedback").fetchone()
        return {"count": row["n"], "average_rating": row["avg"]}

    def metric(self, task: str, mode: str, chosen: str,
               scores: Dict[str, float], confidence: float, review: str) -> None:
        self.conn.execute(
            "INSERT INTO metrics(task,mode,chosen,scores_json,confidence,review,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (clip(task, 2000), mode, chosen, json.dumps(scores),
             confidence, clip(review, 2000), now_iso()))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


@dataclass
class EmotionState:
    labels: List[str]
    intensity: float
    response_style: str
    note: str


class EmotionEngine:
    """Transparent keyword/context heuristic; not clinical emotion recognition."""

    LEXICON = {
        "happy": ["happy", "great", "awesome", "excited", "wonderful", "good"],
        "sad": ["sad", "upset", "lonely", "disappointed", "hurt", "cry"],
        "anxious": ["worried", "anxious", "scared", "nervous", "afraid", "panic"],
        "angry": ["angry", "furious", "irritated", "hate", "annoyed", "mad"],
        "confused": ["confused", "unclear", "don't understand", "lost", "stuck"],
        "curious": ["curious", "wonder", "why", "how", "explore", "investigate"],
        "tired": ["tired", "exhausted", "sleepy", "overwhelmed", "burnt out"],
    }

    def detect(self, text: str, previous: Optional[str] = None) -> EmotionState:
        low = text.lower()
        scores = {name: sum(1 for term in terms if term in low)
                  for name, terms in self.LEXICON.items()}
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        labels = [name for name, score in ranked if score > 0][:2]
        if not labels and previous:
            labels = [previous]
        intensity = min(1.0, sum(scores.values()) / 4.0)
        if not labels:
            return EmotionState([], 0.0, "neutral and clear", "No strong emotion cue detected.")
        primary = labels[0]
        styles = {
            "happy": "upbeat and encouraging", "sad": "gentle and supportive",
            "anxious": "calm, clear and reassuring", "angry": "calm and non-escalating",
            "confused": "patient and step-by-step", "curious": "exploratory and thoughtful",
            "tired": "concise and low-pressure",
        }
        return EmotionState(labels, intensity, styles.get(primary, "balanced"),
                            "Heuristic text cues only; this may be wrong.")


@dataclass
class Candidate:
    name: str
    answer: str
    rationale: str
    risks: List[str]


class ComplexityEstimator:
    def score(self, text: str, context: List[Dict[str, str]]) -> float:
        words = len(text.split())
        score = 0.15 + min(words / 180.0, 0.25)
        if any(x in text.lower() for x in
               ["design", "architecture", "compare", "research", "plan", "build"]):
            score += 0.25
        if "?" in text:
            score += 0.05
        if len(context) >= 5:
            score += 0.05
        if any(x in text.lower() for x in
               ["urgent", "danger", "medical", "legal", "money", "password"]):
            score += 0.15
        return min(1.0, score)


class PrimaryThinker:
    """Builds the first structured response and decomposes the task."""

    def generate(self, task: str, memories: List[Dict[str, Any]]) -> Candidate:
        memory_note = ""
        if memories:
            memory_note = "\nRelevant saved context: " + "; ".join(
                f"{m['mkey']}={m['value'][:160]}" for m in memories[:3])
        steps = [
            "Clarify the desired outcome and constraints.",
            "Break the task into smaller, testable parts.",
            "Choose a feasible first implementation.",
            "Test the result and record what failed or worked.",
        ]
        answer = (
            "A practical first approach is to turn the request into a small "
            "testable workflow.\n\nSuggested sequence:\n"
            + "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))
            + memory_note
        )
        risks = ["The request may need domain-specific facts not present locally."]
        if len(task.split()) < 4:
            risks.append("The request is brief; the intended outcome may be ambiguous.")
        return Candidate("Primary", answer, "Decomposition and feasibility-first planning.", risks)


class CriticalThinker:
    """Audits assumptions, missing inputs, safety and feasibility."""

    def critique(self, task: str, candidate: Candidate) -> List[str]:
        issues = []
        if len(task.split()) < 5:
            issues.append("Intent may be underspecified; ask one focused clarification.")
        if any(w in task.lower() for w in ["always", "never", "guaranteed", "100%"]):
            issues.append("Absolute wording needs evidence and explicit limits.")
        if any(w in task.lower() for w in
               ["delete", "send", "purchase", "install", "execute", "control phone"]):
            issues.append("Consequential action requires explicit user confirmation.")
        if any(w in task.lower() for w in
               ["weapon", "attack", "kill", "explosive"]):
            issues.append("Do not provide operational assistance for harming people.")
        issues.append("Check whether the proposed steps can be verified with observable tests.")
        return issues


class AlternativeThinker:
    """Creates a genuinely different route: prototype-first instead of plan-first."""

    def generate(self, task: str) -> Candidate:
        answer = (
            "Alternative approach: start with the smallest useful experiment.\n\n"
            "1. Select one narrow success criterion.\n"
            "2. Build the smallest version that can meet it.\n"
            "3. Test it with normal, edge and failure cases.\n"
            "4. Compare results against the original goal.\n"
            "5. Expand only after the experiment passes."
        )
        risks = ["A narrow prototype may not cover the full long-term goal."]
        return Candidate("Alternative", answer,
                         "Prototype-first, evidence-driven iteration.", risks)


class ResearchAgent:
    """Searches local knowledge and, only when enabled, Wikipedia's public API."""

    def __init__(self, store: Store):
        self.store = store

    def research(self, query: str, online: bool = False) -> List[Dict[str, str]]:
        results = []
        for item in self.store.search_knowledge(query):
            results.append({
                "title": item["topic"],
                "text": item["content"],
                "source": item["source"],
                "confidence": str(item["confidence"]),
            })
        if online:
            try:
                params = urllib.parse.urlencode({
                    "action": "query", "list": "search", "srsearch": query,
                    "format": "json", "utf8": 1, "srlimit": 3
                })
                request = urllib.request.Request(
                    "https://en.wikipedia.org/w/api.php?" + params,
                    headers={"User-Agent": "CHITTI-Cognitive-Core/2.0 (personal research prototype)"})
                with urllib.request.urlopen(request, timeout=6) as response:
                    data = json.loads(response.read(700000).decode("utf-8"))
                for item in data.get("query", {}).get("search", []):
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    results.append({
                        "title": item.get("title", ""),
                        "text": snippet,
                        "source": "Wikipedia search snippet; verify before relying",
                        "confidence": "0.45",
                    })
            except Exception as exc:
                results.append({
                    "title": "Online research unavailable",
                    "text": f"Offline fallback active ({type(exc).__name__}).",
                    "source": "system",
                    "confidence": "0.0",
                })
        return results[:8]


class DecisionJudge:
    """Scores candidates on feasibility, specificity and risk exposure."""

    def score(self, candidate: Candidate, critique: List[str],
              evidence_count: int) -> float:
        score = 0.55
        score += 0.10 if len(candidate.answer) > 100 else 0.0
        score += 0.08 if "test" in candidate.answer.lower() else 0.0
        score += min(evidence_count, 3) * 0.04
        score -= min(len(candidate.risks), 4) * 0.025
        score -= min(len(critique), 5) * 0.015
        return round(max(0.0, min(1.0, score)), 3)

    def choose(self, candidates: List[Candidate],
               critiques: List[str], evidence_count: int) -> Tuple[Candidate, Dict[str, float]]:
        scores = {}
        for candidate in candidates:
            scores[candidate.name] = self.score(
                candidate, critiques, evidence_count)
        chosen = max(candidates, key=lambda c: scores[c.name])
        return chosen, scores


class SelfReviewAgent:
    """Checks output quality and explicitly reports uncertainty."""

    def review(self, task: str, chosen: Candidate, evidence: List[Dict[str, str]],
               critiques: List[str]) -> Tuple[float, str]:
        checks = []
        if len(chosen.answer.strip()) < 40:
            checks.append("Answer is unusually short.")
        if not evidence:
            checks.append("No matching local or online evidence was retrieved.")
        if critiques:
            checks.append(f"Critical review raised {len(critiques)} issue(s).")
        if not task.strip():
            checks.append("No task text was supplied.")
        confidence = 0.62
        confidence += 0.08 if evidence else 0.0
        confidence -= min(0.20, len(critiques) * 0.025)
        confidence = round(max(0.10, min(0.85, confidence)), 2)
        review = " ".join(checks) if checks else "Basic structural checks passed."
        review += " Confidence is a heuristic quality estimate, not a probability of truth."
        return confidence, review


class OptionalModel:
    """Optional OpenAI-compatible endpoint. Disabled unless configured and enabled."""

    def __init__(self):
        self.enabled = False

    def configured(self) -> bool:
        return bool(os.getenv("CHITTI_API_KEY") and os.getenv("CHITTI_MODEL"))

    def complete(self, prompt: str) -> Optional[str]:
        if not self.enabled or not self.configured():
            return None
        base = os.getenv("CHITTI_API_BASE", "https://api.openai.com/v1").rstrip("/")
        model = os.getenv("CHITTI_MODEL")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content":
                 "You are CHITTI, a careful assistant. Be honest about uncertainty. "
                 "Do not claim consciousness or execute phone actions."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        request = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + os.getenv("CHITTI_API_KEY", ""),
                "Content-Type": "application/json",
            },
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read(1000000).decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            return f"[External model unavailable: {type(exc).__name__}. Local mode remains active.]"


class CognitiveCore:
    def __init__(self, store: Store):
        self.store = store
        self.emotion = EmotionEngine()
        self.complexity = ComplexityEstimator()
        self.primary = PrimaryThinker()
        self.critical = CriticalThinker()
        self.alternative = AlternativeThinker()
        self.research = ResearchAgent(store)
        self.judge = DecisionJudge()
        self.review = SelfReviewAgent()
        self.model = OptionalModel()
        self.mode = "adaptive"
        self.online = False

    def choose_mode(self, task: str, complexity: float,
                    emotion: EmotionState) -> str:
        if self.mode != "adaptive":
            return self.mode
        low = task.lower()
        if emotion.labels and emotion.labels[0] in ("sad", "anxious", "angry", "tired"):
            return "collaborative"
        if complexity >= 0.62 or any(x in low for x in
                                     ["investigate", "design", "compare", "build", "research"]):
            return "autonomous"
        return "collaborative"

    def process(self, task: str) -> str:
        context = self.store.recent_turns()
        previous_emotion = ""
        for turn in reversed(context):
            if turn.get("emotion"):
                previous_emotion = turn["emotion"]
                break
        emotion = self.emotion.detect(task, previous_emotion)
        complexity = self.complexity.score(task, context)
        selected_mode = self.choose_mode(task, complexity, emotion)
        memories = self.store.recall(task)
        evidence = self.research.research(task, self.online)

        candidates = [
            self.primary.generate(task, memories),
            self.alternative.generate(task),
        ]
        critiques = self.critical.critique(task, candidates[0])
        chosen, scores = self.judge.choose(candidates, critiques, len(evidence))
        confidence, review = self.review.review(task, chosen, evidence, critiques)

        external = self.model.complete(task) if self.model.enabled else None
        if external and not external.startswith("[External model unavailable:"):
            chosen.answer = external
            chosen.rationale += " External model supplied a draft; local review remains heuristic."

        self.store.metric(task, selected_mode, chosen.name, scores, confidence, review)
        self.store.add_turn("user", task, ",".join(emotion.labels))
        self.store.add_turn("assistant", chosen.answer, ",".join(emotion.labels))

        output = [
            f"CHITTI Cognitive Core V{VERSION}",
            f"Mode: {selected_mode} | Complexity estimate: {complexity:.2f}",
            f"Context style: {emotion.response_style}",
            "",
            chosen.answer,
            "",
            f"Decision: {chosen.name} | Candidate scores: {scores}",
            f"Confidence estimate: {confidence:.2f}",
            f"Self-review: {review}",
        ]
        if emotion.labels:
            output.insert(3, f"Detected text cues: {', '.join(emotion.labels)} "
                              f"(heuristic, intensity {emotion.intensity:.2f})")
        if evidence:
            output.extend(["", "Retrieved evidence:"])
            for item in evidence[:5]:
                output.append(f"- {item['title']}: {item['text']} "
                              f"[{item['source']}; confidence {item['confidence']}]")
        if critiques:
            output.extend(["", "Critical review:"] + [f"- {x}" for x in critiques])
        if selected_mode == "collaborative":
            output.extend(["", "One useful next question: What constraint or result "
                           "matters most to you?"])
        return "\n".join(output)

    def status(self) -> str:
        feedback = self.store.feedback_summary()
        return (
            f"CHITTI V{VERSION}\n"
            f"Mode: {self.mode}\nOnline research: {'ON' if self.online else 'OFF'}\n"
            f"External model: {'ON' if self.model.enabled else 'OFF'} "
            f"(configured: {self.model.configured()})\n"
            f"Database: {self.store.path}\n"
            f"Feedback records: {feedback['count']}; "
            f"average rating: {feedback['average_rating']}"
        )


HELP = """
Commands:
  /help                         Show commands
  /status                       Show system status
  /mode adaptive|autonomous|collaborative
  /online on|off                Enable/disable optional Wikipedia lookup
  /model on|off                 Enable/disable configured external model
  /remember KEY = VALUE         Save a preference or fact
  /memory                       List saved memories
  /forget ID                    Delete one memory by ID
  /forget all                   Delete all saved memories
  /knowledge TOPIC = CONTENT    Add a local knowledge note
  /feedback good|bad [note]     Rate the last response
  /exit                         Safely close CHITTI

Normal text is treated as a task or conversation.
CHITTI does not execute shell commands or control phone settings.
"""


def split_assignment(text: str) -> Optional[Tuple[str, str]]:
    if "=" not in text:
        return None
    left, right = text.split("=", 1)
    left, right = left.strip(), right.strip()
    return (left, right) if left and right else None


def main() -> None:
    print("=" * 54)
    print(" CHITTI COGNITIVE CORE V2.0")
    print(" Offline-first research prototype | not AGI")
    print("=" * 54)
    try:
        store = Store()
    except Exception as exc:
        print(f"Database initialization failed: {type(exc).__name__}: {exc}")
        return
    core = CognitiveCore(store)
    print("Type /help for commands. Type /exit to close safely.\n")
    try:
        while True:
            try:
                user_text = input("YOU > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCHITTI > Safe shutdown requested.")
                break
            if not user_text:
                continue
            low = user_text.lower()
            if low in ("/exit", "/quit"):
                print("CHITTI > Session saved. Goodbye.")
                break
            elif low == "/help":
                print(HELP)
            elif low == "/status":
                print(core.status())
            elif low.startswith("/mode "):
                mode = low.split(maxsplit=1)[1]
                if mode in ("adaptive", "autonomous", "collaborative"):
                    core.mode = mode
                    print("Mode set to", mode)
                else:
                    print("Choose adaptive, autonomous or collaborative.")
            elif low.startswith("/online "):
                value = low.split(maxsplit=1)[1]
                if value in ("on", "off"):
                    core.online = value == "on"
                    print("Online research", value)
                else:
                    print("Use /online on or /online off.")
            elif low.startswith("/model "):
                value = low.split(maxsplit=1)[1]
                if value in ("on", "off"):
                    core.model.enabled = value == "on"
                    if core.model.enabled and not core.model.configured():
                        print("External model enabled but not configured. "
                              "Set CHITTI_API_KEY and CHITTI_MODEL outside this script.")
                    else:
                        print("External model", value)
                else:
                    print("Use /model on or /model off.")
            elif low.startswith("/remember "):
                pair = split_assignment(user_text[len("/remember "):])
                if pair:
                    store.remember(pair[0], pair[1])
                    print("Saved memory:", pair[0])
                else:
                    print("Format: /remember KEY = VALUE")
            elif low == "/memory":
                rows = store.list_memories()
                if not rows:
                    print("No saved memories yet.")
                for row in rows:
                    print(f"ID {row['id']} [{row['category']}] "
                          f"{row['mkey']} = {row['value']}")
            elif low.startswith("/forget "):
                target = user_text.split(maxsplit=1)[1].strip().lower()
                if target == "all":
                    confirm = input("Delete ALL saved memories? Type DELETE to confirm: ")
                    if confirm == "DELETE":
                        store.forget_all()
                        print("Saved memories deleted.")
                    else:
                        print("Cancelled.")
                elif target.isdigit():
                    print("Memory deleted." if store.forget(int(target))
                          else "No memory found with that ID.")
                else:
                    print("Use /forget ID or /forget all.")
            elif low.startswith("/knowledge "):
                pair = split_assignment(user_text[len("/knowledge "):])
                if pair:
                    store.add_knowledge(pair[0], pair[1])
                    print("Local knowledge note saved.")
                else:
                    print("Format: /knowledge TOPIC = CONTENT")
            elif low.startswith("/feedback "):
                parts = user_text.split(maxsplit=2)
                if len(parts) >= 2 and parts[1].lower() in ("good", "bad"):
                    rating = 1 if parts[1].lower() == "good" else 0
                    note = parts[2] if len(parts) > 2 else ""
                    store.add_feedback("last_response", rating, note)
                    if note:
                        store.remember("feedback_note_" + now_iso(), note,
                                       category="feedback", confidence=0.8)
                    print("Feedback saved for future evaluation.")
                else:
                    print("Use /feedback good [note] or /feedback bad [note].")
            else:
                try:
                    print("\n" + core.process(user_text) + "\n")
                except Exception as exc:
                    print(f"CHITTI internal error: {type(exc).__name__}: {exc}")
                    print("Your message was not executed as a system command.")
    finally:
        store.close()
        print("CHITTI database closed safely.")


if __name__ == "__main__":
    main()

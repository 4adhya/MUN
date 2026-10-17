
import { useState } from "react";
import "./NameEntry.css";

const emojis = [
  "🦊", "🐼", "🦁", "🐸",
  "🐯", "🐻", "🐨", "🐙",
  "🦋", "🐬", "🦄", "🐧",
];

export default function NameEntry({ onEnter }) {
  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState("🦊");

  function handleSubmit(event) {
    event.preventDefault();

    const cleanName = name.trim();
    if (!cleanName) return;

    const profile = { name: cleanName, avatar };

    localStorage.setItem("munProfile", JSON.stringify(profile));

    onEnter(profile);
  }

  return (
    <main className="entry-page">
      <div className="entry-decoration entry-decoration-one" />
      <div className="entry-decoration entry-decoration-two" />

      <form className="entry-card" onSubmit={handleSubmit}>
        <div className="entry-logo">🌍</div>

        <p className="entry-eyebrow">
          DIPLOMACY IN ACTION
        </p>

        <h1>Welcome to MUNVERSE</h1>

        <p className="entry-description">
          Your world. Your perspective.
          <br />
          First, tell us who you are.
        </p>

        <label className="entry-label" htmlFor="mun-name">
          What should we call you?
        </label>

        <input
          id="mun-name"
          className="entry-name-input"
          type="text"
          placeholder="Enter your name..."
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={30}
          autoComplete="nickname"
          required
        />

        <label className="entry-label">
          Choose your avatar
        </label>

        <div className="emoji-grid">
          {emojis.map((emoji) => (
            <button
              key={emoji}
              type="button"
              className={`emoji-button ${
                avatar === emoji ? "emoji-selected" : ""
              }`}
              onClick={() => setAvatar(emoji)}
              aria-label={`Choose ${emoji} avatar`}
              aria-pressed={avatar === emoji}
            >
              {emoji}
            </button>
          ))}
        </div>

        <button className="entry-submit" type="submit">
          Let's Enter <span>→</span>
        </button>

        <p className="entry-footer">
          YOUR JOURNEY INTO DIPLOMACY STARTS HERE
        </p>
      </form>
    </main>
  );
}

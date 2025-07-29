import React, { useState } from "react";
import axios from "axios";
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg = { user: input };
    const history = messages.map(m => ({ 
      user: m.user, 
      bot: typeof m.bot === "string" ? m.bot : JSON.stringify(m.bot) 
    }));
    setMessages(msgs => [...msgs, { user: input }]);
    setInput("");
    try {
      const res = await axios.post("http://localhost:8000/chat", {
        message: input,
        history
      });
      if (res.data.error) {
        setMessages(msgs => [...msgs, { bot: "Error: " + res.data.error }]);
      } else {
        // Always store the answer as a string
        const botResponse = typeof res.data.answer === "string" 
          ? res.data.answer 
          : JSON.stringify(res.data.answer);
        
        setMessages(msgs => [
          ...msgs.slice(0, -1),
          { user: input, bot: botResponse }
        ]);
      }
    } catch (e) {
      setMessages(msgs => [...msgs, { bot: "Server error." }]);
    }
  };

  // Helper to render bot message (string or array of objects)
  const renderBotMessage = (msg) => {
    if (typeof msg === "string") {
      return msg;
    } else if (Array.isArray(msg) && msg.length > 0) {
      return (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                {Object.keys(msg[0]).map((key) => (
                  <th key={key}>{key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {msg.map((row, idx) => (
                <tr key={idx}>
                  {Object.values(row).map((val, i) => (
                    <td key={i}>{typeof val === "object" && val !== null ? JSON.stringify(val) : String(val)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    } else if (Array.isArray(msg) && msg.length === 0) {
      return <span>No records found.</span>;
    } else if (typeof msg === "object" && msg !== null) {
      return <pre>{JSON.stringify(msg, null, 2)}</pre>;
    } else {
      return null;
    }
  };

  return (
    <div style={{ maxWidth: 600, margin: "40px auto", fontFamily: "sans-serif" }}>
      <h2>FIR Chatbot</h2>
      <div className="chat-container">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`message-row${msg.user ? ' user' : ''}`}
          >
            {msg.user && (
              <div className="user-message">
                <b>You:</b> {msg.user}
              </div>
            )}
            {msg.bot && (
              <div className="bot-message">
                <b>Bot:</b> {renderBotMessage(msg.bot)}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="input-area">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Type your question..."
        />
        <button onClick={sendMessage}>Send</button>
      </div>
    </div>
  );
}

export default App;
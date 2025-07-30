import React, { useState } from "react";
import axios from "axios";
import './ChatFIR.css';
import {
  PieChart, Pie, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell
} from 'recharts';

type Message = {
  user?: string;
  bot?: any; // can be string or array
  fir_content?: string; // Add this for FIR content storage
};

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#A28CFF', '#FF6F91', '#6FCF97', '#F2994A'];

function groupByField(data: any[], field: string) {
  const counts: Record<string, number> = {};
  data.forEach(row => {
    const key = row[field] || "Unknown";
    counts[key] = (counts[key] || 0) + 1;
  });
  return Object.entries(counts).map(([key, value]) => ({ [field]: key, count: value }));
}

function ChatFir() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [chartType, setChartType] = useState<string | null>(null);
  const [chartData, setChartData] = useState<any[]>([]);
  const [groupField, setGroupField] = useState("major_head");

  const handleFirOptionClick = (option: string) => {
    sendMessage(option);
  };

  const buildHistory = () => {
    const maxHistory = 8; // Limit history to last 8 turns
    return messages
      .filter(m => m.user || (typeof m.bot === "string" && m.bot.length < 500)) // Only keep short bot replies
      .slice(-maxHistory)
      .map(m => ({
        user: m.user,
        bot: typeof m.bot === "string" && m.bot.length < 500 ? m.bot : undefined, // Ensure bot content is string or undefined
        fir_content: m.fir_content // Include FIR content in history
      }));
  };

  const sendMessage = async (customInput?: string) => {
    const messageToSend = customInput || input;
    if (!messageToSend.trim()) return;
    setMessages(msgs => [...msgs, { user: messageToSend }]);
    setInput("");
    setChartType(null); // Reset chart on new message
    try {
      const res = await axios.post("http://localhost:8000/chat", {
        message: messageToSend,
        history: buildHistory() // Send sanitized history
      });
      if (res.data.error) {
        setMessages(msgs => [...msgs, { bot: "Error: " + res.data.error }]);
      } else {
        let botResponse;
        if (typeof res.data.answer === "string") {
          try {
            const parsed = JSON.parse(res.data.answer); // Attempt to parse JSON string
            botResponse = parsed;
          } catch {
            botResponse = res.data.answer; // If not JSON, use as string
          }
        } else {
          botResponse = res.data.answer;
        }

        // Handle FIR content analysis responses
        if (res.data.fir_content) {
          setMessages(msgs => [
            ...msgs.slice(0, -1),
            { user: messageToSend, bot: botResponse, fir_content: res.data.fir_content }
          ]);
        } else if (Array.isArray(botResponse) && botResponse.length > 0) {
          setMessages(msgs => [
            ...msgs.slice(0, -1),
            { user: messageToSend, bot: botResponse },
            { bot: `Displayed ${botResponse.length} FIRs for: ${messageToSend}` } // Summary for history
          ]);
          setChartData(botResponse);
        } else if (
          typeof botResponse === "string" &&
          botResponse.match(/there (were|are) [0-9]+/i)
        ) {
          const countMatch = botResponse.match(/([0-9]+)/);
          const count = countMatch ? countMatch[1] : "";
          setMessages(msgs => [
            ...msgs.slice(0, -1),
            { user: messageToSend, bot: botResponse },
            { bot: `Counted ${count} FIRs for: ${messageToSend}` } // Summary for history
          ]);
        } else {
          setMessages(msgs => [
            ...msgs.slice(0, -1),
            { user: messageToSend, bot: botResponse }
          ]);
        }
      }
    } catch (e) {
      setMessages(msgs => [...msgs, { bot: "Server error." }]);
    }
  };

  const getChartFields = (data: any[]) => {
    if (!data || data.length === 0) return { label: null, value: null };
    
    const firstRow = data[0];
    const keys = Object.keys(firstRow);
    
    // For grouped data, look for common patterns
    if (keys.includes('count') && keys.includes(groupField)) {
      return { label: groupField, value: 'count' };
    }
    
    // For raw data, use the first string field as label and count as value
    const stringFields = keys.filter(key => 
      typeof firstRow[key] === 'string' && 
      firstRow[key] && 
      firstRow[key].length < 50
    );
    
    if (stringFields.length > 0) {
      return { label: stringFields[0], value: 'count' };
    }
    
    return { label: keys[0], value: 'count' };
  };

  const renderBotMessage = (msg: any) => {
    if (typeof msg === "string") {
      // Check if this is a FIR analysis options message
      if (msg.includes("I see you've provided FIR content") && msg.includes("Please respond with 1, 2, or 3")) {
        return (
          <div className="fir-analysis-options">
            <div className="fir-analysis-title">
              FIR Content Analysis Options
            </div>
            <div className="fir-options-list">
              <div className="fir-option" onClick={() => handleFirOptionClick('1')}>
                <div className="fir-option-number">1</div>
                <div className="fir-option-content">
                  <div className="fir-option-title">Summarize the FIR</div>
                  <div className="fir-option-description">Create a concise summary of the case</div>
                </div>
              </div>
              <div className="fir-option" onClick={() => handleFirOptionClick('2')}>
                <div className="fir-option-number">2</div>
                <div className="fir-option-content">
                  <div className="fir-option-title">Analyze and suggest documents</div>
                  <div className="fir-option-description">Determine case type and suggest relevant reports</div>
                </div>
              </div>
              <div className="fir-option" onClick={() => handleFirOptionClick('3')}>
                <div className="fir-option-number">3</div>
                <div className="fir-option-content">
                  <div className="fir-option-title">Both</div>
                  <div className="fir-option-description">Summarize and analyze the FIR content</div>
                </div>
              </div>
            </div>
          </div>
        );
      }
      return msg;
    } else if (Array.isArray(msg) && msg.length > 0) {
      return (
        <div>
          <div className="table-wrapper">
            <div className="table-header">
              <h4>Found {msg.length} records</h4>
            </div>
            <table>
              <thead>
                <tr>
                  {Object.keys(msg[0]).map((key) => (
                    <th key={key}>{key.replace(/_/g, ' ').toUpperCase()}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {msg.map((row, idx) => (
                  <tr key={idx}>
                    {Object.values(row).map((val, i) => (
                      <td key={i}>
                        {typeof val === "object" && val !== null ? JSON.stringify(val) : String(val)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Grouping dropdown and chart suggestion */}
          <div className="grouping-dropdown">
            <label htmlFor="groupField">Group chart by: </label>
            <select
              id="groupField"
              value={groupField}
              onChange={e => setGroupField(e.target.value)}
            >
              <option value="major_head">Major Head</option>
              <option value="district">District</option>
              <option value="ipc_sections">IPC Sections</option>
              <option value="case_status">Case Status</option>
              <option value="police_station">Police Station</option>
            </select>
          </div>
          <div className="viz-suggestion">
            <span>Would you like to see this data as a chart?</span>
            <button onClick={() => setChartType('pie')}>Pie Chart</button>
            <button onClick={() => setChartType('bar')}>Bar Chart</button>
            <button onClick={() => setChartType('line')}>Line Chart</button>
          </div>
        </div>
      );
    } else if (Array.isArray(msg) && msg.length === 0) {
      return <span className="no-records">No records found.</span>;
    } else if (typeof msg === "object" && msg !== null) {
      return <pre className="json-display">{JSON.stringify(msg, null, 2)}</pre>;
    } else {
      return null;
    }
  };

  const renderChart = () => {
    if (!chartType || !chartData || chartData.length === 0) return null;
    let dataForChart = chartData;
    const { label, value } = getChartFields(chartData); // getChartFields uses groupField

    // For pie/bar/line chart, if not already grouped, group by the selected field
    if (
      (chartType === 'pie' || chartType === 'bar' || chartType === 'line') &&
      chartData.length > 0 &&
      label && // Add null check for label
      (!chartData[0].count || !chartData[0][label]) // Check if data is already aggregated
    ) {
      dataForChart = groupByField(chartData, groupField);
    }

    if (!label || !value) return <div>No suitable data for charting.</div>;
    return (
      <div className="chart-container">
        {chartType === 'pie' && (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={dataForChart}
                dataKey="count" // Always use 'count' for grouped data
                nameKey={label}
                cx="50%"
                cy="50%"
                outerRadius={100}
                fill="#8884d8"
                label
              >
                {dataForChart.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        )}
        {chartType === 'bar' && (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={dataForChart}>
              <XAxis dataKey={label} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="count" fill="#8884d8" />
            </BarChart>
          </ResponsiveContainer>
        )}
        {chartType === 'line' && (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={dataForChart}>
              <XAxis dataKey={label} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="count" stroke="#8884d8" />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div style={{ marginTop: 10 }}>
          <button onClick={() => setChartType(null)}>Hide Chart</button>
        </div>
      </div>
    );
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <h2>FIR Chatbot</h2>
        <p>Ask questions about FIR data or paste FIR content for analysis</p>
      </div>
      
      <div className="messages-container">
        {messages.map((msg, i) => (
          <div key={i} className={`message-row${msg.user ? ' user' : ''}`}>
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
        {renderChart()}
      </div>
      
      <div className="input-area">
        <input 
          value={input} 
          onChange={e => setInput(e.target.value)} 
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Ask about FIR data or paste FIR content for analysis..."
        />
        <button onClick={sendMessage}>Send</button>
      </div>
    </div>
  );
}

export default ChatFir;
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
  suggested_reports?: string[]; // Add this for suggested reports
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

function parseFirSummary(summaryText: string) {
  const lines = summaryText.split('\n').filter(line => line.trim());
  const summaryData: Array<{category: string, details: string}> = [];
  
  lines.forEach(line => {
    const trimmedLine = line.trim();
    
    // Try different patterns to match summary lines
    let match = null;
    
    // Pattern 1: Tab-separated format "Case Type and Category\tRobbery and Assault"
    if (trimmedLine.includes('\t')) {
      const parts = trimmedLine.split('\t');
      if (parts.length >= 2) {
        summaryData.push({
          category: parts[0].trim(),
          details: parts.slice(1).join('\t').trim()
        });
      }
    }
    // Pattern 2: "1. Case Type and Category: Robbery and Assault"
    else if (trimmedLine.match(/^\d+\./)) {
      match = trimmedLine.match(/^\d+\.\s*(.+?):\s*(.+)/);
    }
    // Pattern 3: "Case Type and Category: Robbery and Assault"
    else if (trimmedLine.includes(':')) {
      match = trimmedLine.match(/^(.+?):\s*(.+)/);
    }
    // Pattern 4: "Case Type and Category - Robbery and Assault"
    else if (trimmedLine.includes(' - ')) {
      match = trimmedLine.match(/^(.+?)\s*-\s*(.+)/);
    }
    
    if (match) {
      summaryData.push({
        category: match[1].trim(),
        details: match[2].trim()
      });
    }
  });
  
  // If no structured data found, return the raw text
  if (summaryData.length === 0) {
    return [{ category: "Summary", details: summaryText }];
  }
  
  return summaryData;
}

function ChatFir() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [chartType, setChartType] = useState<string | null>(null);
  const [chartData, setChartData] = useState<any[]>([]);
  const [groupField, setGroupField] = useState("major_head");
  const [showReportForm, setShowReportForm] = useState(false);
  const [currentReportForm, setCurrentReportForm] = useState<any>(null);
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [showDownloadOptions, setShowDownloadOptions] = useState(false);
  const [formDataForDownload, setFormDataForDownload] = useState<{formData: Record<string, any>, reportType: string} | null>(null);

  const handleFirOptionClick = (option: string) => {
    sendMessage(option);
  };

  const handleReportClick = async (reportType: string) => {
    console.log('Clicking report:', reportType);
    
    try {
      const url = `http://localhost:8000/report-form/${encodeURIComponent(reportType)}`;
      console.log('Making request to:', url);
      
      const response = await axios.get(url);
      console.log('Report form response:', response.data);
      
      if (response.data.error) {
        console.error('Report form error:', response.data.error);
        alert(`Report form not found: ${response.data.error}`);
        return;
      }
      
      setCurrentReportForm(response.data);
      setShowReportForm(true);
      setFormData({});
      console.log('Form opened successfully');
      
    } catch (error: any) {
      console.error('Error fetching report form:', error);
      console.error('Error response:', error.response?.data);
      alert(`Error loading report form: ${error.message}`);
    }
  };

  const testReportForm = async () => {
    console.log('Testing report form...');
    try {
      const response = await axios.get('http://localhost:8000/test-report');
      console.log('Test response:', response.data);
      setCurrentReportForm(response.data);
      setShowReportForm(true);
      setFormData({});
    } catch (error) {
      console.error('Test error:', error);
      alert('Test failed - backend not running');
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    // Get the report type from the current form
    const reportType = currentReportForm?.title || "Report";
    console.log('Submitting form for report type:', reportType);
    console.log('Form data:', formData);
    
    // Show download options
    setShowDownloadOptions(true);
    setFormDataForDownload({ formData, reportType });
  };

  const handleFormInputChange = (fieldName: string, value: any) => {
    setFormData((prev: Record<string, any>) => ({
      ...prev,
      [fieldName]: value
    }));
  };

  const handleDownload = async (format: 'pdf' | 'excel' | 'docs') => {
    if (!formDataForDownload) return;
    
    try {
      const { formData, reportType } = formDataForDownload;
      console.log(`Downloading ${format} for report type:`, reportType);
      
      const response = await axios.post(
        `http://localhost:8000/generate-${format}`,
        {
          formData: formData,
          reportType: reportType
        },
        {
          responseType: 'blob'
        }
      );
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${reportType.replace(' ', '_')}_${new Date().toISOString().slice(0, 10)}.${format === 'excel' ? 'xlsx' : format === 'docs' ? 'docx' : 'pdf'}`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      
      // Close download options
      setShowDownloadOptions(false);
      setFormDataForDownload(null);
      setShowReportForm(false);
      setCurrentReportForm(null);
      setFormData({});
      
    } catch (error: any) {
      console.error(`Error downloading ${format}:`, error);
      alert(`Error downloading ${format.toUpperCase()}: ${error.message}`);
    }
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
          console.log('Backend response:', res.data);
          console.log('Suggested reports:', res.data.suggested_reports);
          setMessages(msgs => [
            ...msgs.slice(0, -1),
            { 
              user: messageToSend, 
              bot: botResponse, 
              fir_content: res.data.fir_content,
              suggested_reports: res.data.suggested_reports || []
            }
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
    
    // For raw data, use the selected group field as label and count as value
    if (keys.includes(groupField)) {
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

  const renderBotMessage = (msg: any): JSX.Element | string | null => {
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
                  <div className="fir-option-title">Summarize</div>
                  <div className="fir-option-description">Create summary</div>
                </div>
              </div>
              <div className="fir-option" onClick={() => handleFirOptionClick('2')}>
                <div className="fir-option-number">2</div>
                <div className="fir-option-content">
                  <div className="fir-option-title">Analyze</div>
                  <div className="fir-option-description">Suggest documents</div>
                </div>
              </div>
              <div className="fir-option" onClick={() => handleFirOptionClick('3')}>
                <div className="fir-option-number">3</div>
                <div className="fir-option-content">
                  <div className="fir-option-title">Both</div>
                  <div className="fir-option-description">Summary & analysis</div>
                </div>
              </div>
            </div>
          </div>
        );
      }
      
      // Check if this is a FIR summary response
      if (msg.includes("**FIR Summary:**")) {
        const summaryContent = msg.replace("**FIR Summary:**", "").trim();
        const summaryData = parseFirSummary(summaryContent);
        
        // Debug: If no structured data found, show the raw content
        if (summaryData.length === 0 || (summaryData.length === 1 && summaryData[0].category === "Summary")) {
          return (
            <div className="fir-summary-table">
              <div className="table-header">
                <h4>FIR Summary</h4>
              </div>
              <div style={{ padding: '15px', whiteSpace: 'pre-wrap' }}>
                {summaryContent}
              </div>
            </div>
          );
        }
        
        return (
          <div className="fir-summary-table">
            <div className="table-header">
              <h4>FIR Summary</h4>
            </div>
            <table>
              <tbody>
                {summaryData.map((item, index) => (
                  <tr key={index}>
                    <th>{item.category}</th>
                    <td>{item.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      
      // Check if this is a FIR analysis response
      if (msg.includes("**Suggested Reports for this FIR:**") || msg.includes("**FIR Analysis and Document Suggestions:**") || msg.includes("After analyzing the detailed FIR content")) {
        return (
          <div className="fir-analysis-response">
            <div className="analysis-header">
              <h4>FIR Analysis & Document Suggestions</h4>
            </div>
            <div style={{ padding: '15px', whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>
              {msg}
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

    // For all chart types, if not already grouped, group by the selected field
    if (
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

  const renderReportLinks = (suggestedReports: string[]) => {
    if (!suggestedReports || suggestedReports.length === 0) return null;
    const letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'];
    return (
      <div className="report-links-container">
        <div className="report-links-header"><h4>Click on a report to generate:</h4></div>
        <div className="report-links-list">
          {suggestedReports.map((report, index) => (
            <div key={index} className="report-link-label" onClick={() => handleReportClick(report)}>
              {letters[index]}) {report}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderReportForm = () => {
    if (!showReportForm || !currentReportForm) return null;

    return (
      <div className="modal-overlay">
        <div className="modal-content">
          <div className="modal-header">
            <h3>{currentReportForm.title}</h3>
            <button 
              className="modal-close"
              onClick={() => {
                setShowReportForm(false);
                setCurrentReportForm(null);
                setFormData({});
              }}
            >
              ×
            </button>
          </div>
          <form onSubmit={handleFormSubmit} className="report-form">
            {currentReportForm.fields.map((field: any, index: number) => (
              <div key={index} className="form-field">
                <label htmlFor={field.name}>
                  {field.label}
                  {field.required && <span className="required">*</span>}
                </label>
                {field.type === 'textarea' ? (
                  <textarea
                    id={field.name}
                    name={field.name}
                    value={formData[field.name] || ''}
                    onChange={(e) => handleFormInputChange(field.name, e.target.value)}
                    required={field.required}
                    rows={4}
                  />
                ) : field.type === 'select' ? (
                  <select
                    id={field.name}
                    name={field.name}
                    value={formData[field.name] || ''}
                    onChange={(e) => handleFormInputChange(field.name, e.target.value)}
                    required={field.required}
                  >
                    <option value="">Select {field.label}</option>
                    {field.options.map((option: string) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    id={field.name}
                    name={field.name}
                    value={formData[field.name] || ''}
                    onChange={(e) => handleFormInputChange(field.name, e.target.value)}
                    required={field.required}
                  />
                )}
              </div>
            ))}
            <div className="form-actions">
              <button type="submit" className="submit-btn">Generate Report</button>
              <button 
                type="button" 
                className="cancel-btn"
                onClick={() => {
                  setShowReportForm(false);
                  setCurrentReportForm(null);
                  setFormData({});
                }}
              >
                Cancel
              </button>
            </div>
          </form>
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
          <div key={i} className={`message-row${msg.user ? ' user' : ' bot'}`}>
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
            {msg.suggested_reports && renderReportLinks(msg.suggested_reports)}
          </div>
        ))}
        {renderChart()}
        {renderReportForm()}
        {showDownloadOptions && (
          <div className="modal-overlay">
            <div className="modal-content download-options">
              <div className="modal-header">
                <h3>Download Report</h3>
                <button 
                  className="modal-close"
                  onClick={() => {
                    setShowDownloadOptions(false);
                    setFormDataForDownload(null);
                  }}
                >
                  ×
                </button>
              </div>
              <div className="download-options-content">
                <p>Choose a format to download your report:</p>
                <div className="download-buttons">
                  <button 
                    onClick={() => handleDownload('pdf')}
                    className="download-btn pdf-btn"
                  >
                    📄 Generate PDF
                  </button>
                  <button 
                    onClick={() => handleDownload('excel')}
                    className="download-btn excel-btn"
                  >
                    📊 Generate Excel
                  </button>
                  <button 
                    onClick={() => handleDownload('docs')}
                    className="download-btn docs-btn"
                  >
                    📝 Generate Word Doc
                  </button>
                  <button 
                    onClick={() => {
                      setShowDownloadOptions(false);
                      setFormDataForDownload(null);
                    }}
                    className="download-btn cancel-btn"
                  >
                    ❌ Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      
      <div className="input-area">
        <input 
          value={input} 
          onChange={e => setInput(e.target.value)} 
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Ask about FIR data or paste FIR content for analysis..."
        />
        <button onClick={() => sendMessage()}>Send</button>
        <button onClick={testReportForm} style={{background: '#ffc107', color: '#000'}}>Test Report</button>
      </div>
    </div>
  );
}

export default ChatFir;
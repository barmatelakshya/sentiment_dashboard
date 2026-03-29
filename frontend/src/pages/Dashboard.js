import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import { ArrowUp, ArrowDown, Minus, WifiHigh, WifiSlash } from '@phosphor-icons/react';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS  = process.env.REACT_APP_WS_URL  || 'ws://localhost:8000';

const COLORS = { positive: '#0055FF', negative: '#FF2A2A', neutral: '#FFC000' };

function sentimentColor(s) { return COLORS[s] || '#737373'; }
function SentimentIcon({ s }) {
  if (s === 'positive') return <ArrowUp weight="bold" color={COLORS.positive} />;
  if (s === 'negative') return <ArrowDown weight="bold" color={COLORS.negative} />;
  return <Minus weight="bold" color={COLORS.neutral} />;
}

export default function Dashboard() {
  const [feed, setFeed]           = useState([]);
  const [trends, setTrends]       = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  const connect = () => {
    const ws = new WebSocket(`${WS}/api/ws/sentiment`);
    ws.onopen  = () => setConnected(true);
    ws.onclose = () => { setConnected(false); setTimeout(connect, 5000); };
    ws.onerror = () => setConnected(false);
    ws.onmessage = ({ data }) => {
      const msg = JSON.parse(data);
      if (msg.type === 'init') {
        setFeed(msg.articles);
        setTrends(msg.trends);
      }
      if (msg.type === 'new_sentiment') {
        setFeed(prev => prev.some(a => a.id === msg.data.id) ? prev : [msg.data, ...prev.slice(0, 49)]);
        toast.success(`${msg.data.sentiment} — ${msg.data.source}`);
      }
      if (msg.type === 'trends') {
        setTrends(msg.data);
      }
    };
    wsRef.current = ws;
  };

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, []);

  const dist = trends?.distribution || {};
  const pieData = Object.entries(dist).map(([name, value]) => ({ name, value, color: COLORS[name] }));

  return (
    <div style={{ padding: '1.5rem', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1px', paddingLeft: '0' }}
           className="cell grid-border">
        <img src="/logo.svg" alt="Sentiment Dashboard" style={{ height: '120px', marginLeft: '1rem' }} />
        <span className="mono" style={{ fontSize: 11, color: connected ? '#22c55e' : '#ef4444', display: 'flex', alignItems: 'center', gap: 6 }}>
          {connected ? <WifiHigh /> : <WifiSlash />}
          {connected ? 'LIVE' : 'RECONNECTING'}
        </span>
      </div>

      {/* Stats row */}
      <div className="grid-border" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: '1px' }}>
        {['positive', 'negative', 'neutral'].map(s => (
          <div key={s} className="cell" style={{ borderTop: `3px solid ${COLORS[s]}` }}>
            <div className="mono" style={{ fontSize: 10, color: '#737373', textTransform: 'uppercase' }}>{s}</div>
            <div style={{ fontSize: '2rem', fontWeight: 700, color: COLORS[s] }}>{dist[s] ?? 0}</div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid-border" style={{ gridTemplateColumns: '2fr 1fr', marginBottom: '1px' }}>
        <div className="cell">
          <div className="mono" style={{ fontSize: 10, color: '#737373', marginBottom: '1rem' }}>TREND</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trends?.time_series || []}>
              <CartesianGrid stroke="#1a1a1a" strokeDasharray="0" />
              <XAxis dataKey="timestamp" hide />
              <YAxis stroke="#737373" tick={{ fontSize: 10, fontFamily: 'IBM Plex Mono' }} />
              <Tooltip
                contentStyle={{ background: '#141414', border: '1px solid #262626', borderRadius: 0 }}
                itemStyle={{ fontFamily: 'IBM Plex Mono', fontSize: 10 }}
              />
              {['positive', 'negative', 'neutral'].map(k => (
                <Line key={k} type="linear" dataKey={k} stroke={COLORS[k]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="cell" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div className="mono" style={{ fontSize: 10, color: '#737373', marginBottom: '1rem', alignSelf: 'flex-start' }}>DISTRIBUTION</div>
          <PieChart width={180} height={180}>
            <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={0} dataKey="value">
              {pieData.map((e, i) => <Cell key={i} fill={e.color} />)}
            </Pie>
            <Tooltip contentStyle={{ background: '#141414', border: '1px solid #262626', borderRadius: 0 }}
                     itemStyle={{ fontFamily: 'IBM Plex Mono', fontSize: 10 }} />
          </PieChart>
        </div>
      </div>

      {/* Live Feed */}
      <div className="cell" style={{ border: '1px solid #262626' }}>
        <div className="mono" style={{ fontSize: 10, color: '#737373', marginBottom: '1rem' }}>LIVE FEED</div>
        <div style={{ maxHeight: 500, overflowY: 'auto' }}>
          {feed.length === 0 && (
            <div className="mono" style={{ color: '#737373', fontSize: 12 }}>Waiting for data...</div>
          )}
          {feed.map((item, i) => (
            <div key={item.id || i} className="feed-item" style={{ borderColor: sentimentColor(item.sentiment) }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                    <span className="tag" style={{ background: sentimentColor(item.sentiment), color: item.sentiment === 'neutral' ? '#000' : '#fff' }}>
                      {item.sentiment}
                    </span>
                    <span className="mono" style={{ fontSize: 10, color: '#737373' }}>{item.source}</span>
                  </div>
                  <a href={item.url} target="_blank" rel="noreferrer"
                     style={{ color: '#fff', textDecoration: 'none', fontWeight: 600, fontSize: 14 }}>
                    {item.title}
                  </a>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                  <SentimentIcon s={item.sentiment} />
                  <span className="mono" style={{ fontSize: 10, color: '#737373' }}>
                    {(item.score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

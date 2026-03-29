import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import Dashboard from './pages/Dashboard';
import { Toaster } from 'sonner';

ReactDOM.createRoot(document.getElementById('root')).render(
  <>
    <Toaster theme="dark" position="bottom-right" />
    <Dashboard />
  </>
);

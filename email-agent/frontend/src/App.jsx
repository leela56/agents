import { useState, useCallback } from 'react';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import EmailList from './components/EmailList';
import EmailDetail from './components/EmailDetail';
import './App.css';

export default function App() {
  const [activeCategory, setActiveCategory] = useState(null);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);

  const handleProcessComplete = useCallback(() => {
    setRefreshKey(k => k + 1);
  }, []);

  const handleSelectEmail = useCallback((email) => {
    setSelectedEmail(email);
  }, []);

  const handleCategoryChange = useCallback((cat) => {
    setActiveCategory(cat);
    setSelectedEmail(null);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedEmail(null);
  }, []);

  return (
    <>
      <Header
        onProcessComplete={handleProcessComplete}
        isProcessing={isProcessing}
        setIsProcessing={setIsProcessing}
      />
      <div className="app-body">
        <Sidebar
          activeCategory={activeCategory}
          onCategoryChange={handleCategoryChange}
          refreshKey={refreshKey}
        />
        <main className="app-main">
          <EmailList
            category={activeCategory}
            selectedEmailId={selectedEmail?.id}
            onSelectEmail={handleSelectEmail}
            refreshKey={refreshKey}
          />
          <EmailDetail
            emailId={selectedEmail?.id}
            onClose={handleCloseDetail}
          />
        </main>
      </div>

      {/* Background ambient gradient */}
      <div className="ambient-bg" aria-hidden="true" />
    </>
  );
}

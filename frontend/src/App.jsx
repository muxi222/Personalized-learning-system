import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import QuestionSubmit from './pages/QuestionSubmit'
import QuestionDetail from './pages/QuestionDetail'
import QuestionList from './pages/QuestionList'
import ImageQuestionGroup from './pages/ImageQuestionGroup'
import ReviewPage from './pages/ReviewPage'
import ExamUpload from './pages/ExamUpload'
import CorrectionHistory from './pages/CorrectionHistory'
import CorrectionDetail from './pages/CorrectionDetail'
import LearningAdvisor from './pages/LearningAdvisor'
import TaskDetail from './pages/TaskDetail'
import Login from './pages/Login'
import Register from './pages/Register'
import PageErrorBoundary from './components/PageErrorBoundary'

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuthStore()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return children
}

function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      {/* Protected routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="submit" element={<QuestionSubmit />} />
        <Route path="tasks/:taskId" element={<TaskDetail />} />
        <Route path="exam-upload" element={<ExamUpload />} />
        <Route path="corrections" element={<CorrectionHistory />} />
        <Route path="corrections/:id" element={<CorrectionDetail />} />
        <Route path="learning" element={<LearningAdvisor />} />
        <Route path="questions" element={<QuestionList />} />
        <Route
          path="questions/:id"
          element={
            <PageErrorBoundary>
              <QuestionDetail />
            </PageErrorBoundary>
          }
        />
        <Route path="questions/image/:imageId" element={<ImageQuestionGroup />} />
        <Route path="review" element={<ReviewPage />} />
      </Route>

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App

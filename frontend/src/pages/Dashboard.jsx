import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { questionApi, feedbackApi } from '../lib/api'
import { SUBJECT_NAMES_CN } from '../config/moduleRouting'
import { Camera, PlusCircle, Sparkles, ArrowRight, ChevronRight } from 'lucide-react'

export default function Dashboard() {
  const [subject, setSubject] = useState('')
  const questionsQuery = useQuery({
    queryKey: ['questions', { page: 1, page_size: 5, subject, group_by: 'none' }],
    queryFn: () => questionApi.list({ page: 1, page_size: 5, group_by: 'none', subject: subject || undefined }),
  })
  const reviewQuery = useQuery({
    queryKey: ['review-due', { limit: 5, subject }],
    queryFn: () => questionApi.getDueForReview({ limit: 5, subject: subject || undefined }),
  })
  const statsQuery = useQuery({
    queryKey: ['feedback-stats', { subject }],
    queryFn: () => feedbackApi.getStats(subject || undefined),
  })
  const recentQuestions = questionsQuery.data?.data?.items || []
  const reviewQuestions = reviewQuery.data?.data || []
  const stats = statsQuery.data?.data
  const questionLink = (question) => '/questions/' + question.id + (question.subject ? '?subject=' + encodeURIComponent(question.subject) : '')
  const numberText = (query, value) => query.isPending ? '...' : query.isError ? '-' : value
  const average = stats?.average_rating == null ? '-' : Number(stats.average_rating).toFixed(1)
  const feedbackRate = stats?.feedback_rate == null ? '-' : (Number(stats.feedback_rate) * 100).toFixed(0) + '%'

  return (
    <div className="animate-fade-in">
      <div className="section-heading">
        <h1>我的学习</h1>
        <select aria-label="统计学科" className="input w-auto text-sm" value={subject} onChange={event => setSubject(event.target.value)}>
          <option value="">全部学科</option>
          {Object.entries(SUBJECT_NAMES_CN).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <div className="dashboard-stats">
        {[
          { label: '错题总数', value: numberText(questionsQuery, questionsQuery.data?.data?.total || 0), color: '#4e83ee' },
          { label: '待复习（最近 5 题）', value: numberText(reviewQuery, reviewQuestions.length), color: '#ce9b48' },
          { label: '平均评分', value: numberText(statsQuery, average), color: '#46a68f' },
          { label: '反馈率', value: numberText(statsQuery, feedbackRate), color: '#6c86b8' },
        ].map(item => <div className="dashboard-stat" key={item.label}><span>{item.label}</span><strong style={{ color: item.color }}>{item.value}</strong></div>)}
      </div>
      <div className="dashboard-actions">
        {[
          { to: '/exam-upload', icon: Camera, title: 'AI 智能批改', subtitle: '试卷与作业' },
          { to: '/submit', icon: PlusCircle, title: '录入新错题', subtitle: '我的错题积累' },
          { to: '/companion', icon: Sparkles, title: '小书童', subtitle: '我的学习伙伴' },
        ].map(({ to, icon: Icon, title, subtitle }) => <Link className="learning-action" to={to} key={to}><Icon /><span><strong>{title}</strong><small>{subtitle}</small></span><ArrowRight className="action-arrow" /></Link>)}
      </div>
      <section className="dashboard-section">
        <div className="section-heading"><h2>最近错题</h2><Link to="/questions">全部错题<ChevronRight size={14} /></Link></div>
        {questionsQuery.isPending ? <p className="empty-line">正在加载错题...</p> : questionsQuery.isError ? <p className="empty-line">错题暂时无法加载 <button className="text-primary-600" onClick={() => questionsQuery.refetch()}>重试</button></p> : recentQuestions.length ? (
          <div className="question-rows">{recentQuestions.map(question => <Link className="question-row" to={questionLink(question)} key={question.id}>
            <span className="badge-primary">{SUBJECT_NAMES_CN[question.subject] || question.subject || '其他'}</span>
            <div><strong>{question.title || question.content?.slice(0, 70) || '题目内容'}</strong><small>{new Date(question.created_at).toLocaleDateString('zh-CN')}</small></div><ArrowRight />
          </Link>)}</div>
        ) : <p className="empty-line">还没有错题记录 <Link className="text-primary-600" to="/submit">录入第一道错题</Link></p>}
      </section>
      <section className="dashboard-section">
        <div className="section-heading"><h2>复习清单</h2><Link to="/review">开始复习<ChevronRight size={14} /></Link></div>
        {reviewQuery.isPending ? <p className="empty-line">正在加载复习清单...</p> : reviewQuery.isError ? <p className="empty-line">复习清单暂时无法加载 <button className="text-primary-600" onClick={() => reviewQuery.refetch()}>重试</button></p> : reviewQuestions.length ? (
          <div className="question-rows">{reviewQuestions.map(question => <Link className="question-row" to={questionLink(question)} key={question.id}>
            <span className="badge-warning">待复习</span><div><strong>{question.title || question.content?.slice(0, 70) || '题目内容'}</strong><small>{SUBJECT_NAMES_CN[question.subject] || question.subject} · 已复习 {question.review_count || 0} 次</small></div><ArrowRight />
          </Link>)}</div>
        ) : <p className="empty-line">今天暂无待复习的错题</p>}
      </section>
    </div>
  )
}

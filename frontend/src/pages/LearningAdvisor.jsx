import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  Target,
  TrendingUp,
  Calendar,
  Clock,
  BookOpen,
  Award,
  ChevronRight,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Flame,
  Zap,
  BarChart3
} from 'lucide-react'

// 获取 token 的辅助函数
const getAuthToken = () => {
  const authStorage = localStorage.getItem('auth-storage')
  if (authStorage) {
    const { state } = JSON.parse(authStorage)
    return state?.token
  }
  return null
}

// API 调用函数
const learningApi = {
  getProfile: () => {
    const token = getAuthToken()
    return fetch('/api/v1/learning/profile', {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    }).then(res => res.json())
  },

  getRecommendations: (goal, limit = 5) => {
    const token = getAuthToken()
    return fetch(
      `/api/v1/learning/recommendations?goal=${goal}&limit=${limit}`,
      { headers: token ? { 'Authorization': `Bearer ${token}` } : {} }
    ).then(res => res.json())
  },

  getStudyPlan: (goal, days = 7) => {
    const token = getAuthToken()
    return fetch(
      `/api/v1/learning/study-plan?goal=${goal}&days=${days}`,
      { headers: token ? { 'Authorization': `Bearer ${token}` } : {} }
    ).then(res => res.json())
  },

  getSummary: (days = 7) => {
    const token = getAuthToken()
    return fetch(
      `/api/v1/learning/summary?days=${days}`,
      { headers: token ? { 'Authorization': `Bearer ${token}` } : {} }
    ).then(res => res.json())
  },
}

const GOAL_OPTIONS = [
  { value: 'improve_weak_points', label: '强化薄弱点', icon: Target, color: 'text-red-400' },
  { value: 'prepare_exam', label: '备考复习', icon: BookOpen, color: 'text-amber-400' },
  { value: 'daily_practice', label: '每日练习', icon: Calendar, color: 'text-blue-400' },
  { value: 'review_mistakes', label: '错题复习', icon: AlertTriangle, color: 'text-purple-400' },
]

export default function LearningAdvisor() {
  const [selectedGoal, setSelectedGoal] = useState('improve_weak_points')
  const [planDays, setPlanDays] = useState(7)

  // 获取学习画像
  const { data: profile, isLoading: profileLoading } = useQuery({
    queryKey: ['learning-profile'],
    queryFn: learningApi.getProfile,
  })

  // 获取学习建议
  const { data: recommendations } = useQuery({
    queryKey: ['recommendations', selectedGoal],
    queryFn: () => learningApi.getRecommendations(selectedGoal),
  })

  // 获取学习计划
  const { data: studyPlan } = useQuery({
    queryKey: ['study-plan', selectedGoal, planDays],
    queryFn: () => learningApi.getStudyPlan(selectedGoal, planDays),
  })

  // 获取学习总结
  const { data: summary } = useQuery({
    queryKey: ['learning-summary'],
    queryFn: () => learningApi.getSummary(7),
  })

  if (profileLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Brain className="w-16 h-16 text-primary-400 mx-auto mb-4 animate-pulse" />
          <p className="text-slate-400">正在分析你的学习数据...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-12 h-12 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
            <Brain className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-display text-3xl font-bold text-white">
              AI 学习顾问
            </h1>
            <p className="text-slate-400">
              基于你的学习数据，为你量身定制学习建议
            </p>
          </div>
        </div>
      </div>

      {/* 学习画像卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="card p-6 bg-gradient-to-br from-primary-500/10 to-transparent">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">总做题数</span>
            <BookOpen className="w-5 h-5 text-primary-400" />
          </div>
          <p className="text-3xl font-bold text-white">{profile?.total_questions || 0}</p>
        </div>

        <div className="card p-6 bg-gradient-to-br from-emerald-500/10 to-transparent">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">正确率</span>
            <TrendingUp className="w-5 h-5 text-emerald-400" />
          </div>
          <p className="text-3xl font-bold text-white">
            {((profile?.overall_accuracy || 0) * 100).toFixed(0)}%
          </p>
        </div>

        <div className="card p-6 bg-gradient-to-br from-amber-500/10 to-transparent">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">连续学习</span>
            <Flame className="w-5 h-5 text-amber-400" />
          </div>
          <p className="text-3xl font-bold text-white">{profile?.streak_days || 0} 天</p>
        </div>

        <div className="card p-6 bg-gradient-to-br from-purple-500/10 to-transparent">
          <div className="flex items-center justify-between mb-2">
            <span className="text-slate-400 text-sm">最佳学习时间</span>
            <Clock className="w-5 h-5 text-purple-400" />
          </div>
          <p className="text-xl font-bold text-white">{profile?.optimal_study_time || '晚上'}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧 - 学习目标选择 & 薄弱点 */}
        <div className="space-y-6">
          {/* 学习目标 */}
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Target className="w-5 h-5 text-primary-400" />
              选择学习目标
            </h3>
            <div className="space-y-2">
              {GOAL_OPTIONS.map(({ value, label, icon: Icon, color }) => (
                <button
                  key={value}
                  onClick={() => setSelectedGoal(value)}
                  className={`w-full p-4 rounded-xl border-2 transition-all flex items-center gap-3 ${
                    selectedGoal === value
                      ? 'border-primary-500 bg-primary-500/10'
                      : 'border-slate-700 hover:border-slate-600'
                  }`}
                >
                  <Icon className={`w-5 h-5 ${color}`} />
                  <span className={selectedGoal === value ? 'text-white' : 'text-slate-300'}>
                    {label}
                  </span>
                  {selectedGoal === value && (
                    <CheckCircle2 className="w-5 h-5 text-primary-400 ml-auto" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* 薄弱知识点 */}
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
              薄弱知识点
            </h3>
            {profile?.weak_points?.length > 0 ? (
              <div className="space-y-3">
                {profile.weak_points.slice(0, 5).map((wp, index) => (
                  <div key={index} className="p-3 bg-slate-800/50 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-white font-medium text-sm">
                        {wp.knowledge_point}
                      </span>
                      <span className="text-red-400 text-xs">
                        错误 {wp.error_count} 次
                      </span>
                    </div>
                    <div className="w-full bg-slate-700 rounded-full h-2">
                      <div
                        className="bg-red-500 h-2 rounded-full transition-all"
                        style={{ width: `${wp.error_rate * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <Award className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
                <p className="text-slate-400">太棒了！暂无明显薄弱点</p>
              </div>
            )}
          </div>

          {/* 学科分布 */}
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-blue-400" />
              学科分布
            </h3>
            <div className="space-y-3">
              {Object.entries(profile?.subject_stats || {}).map(([subject, stats]) => (
                <div key={subject}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-slate-300 text-sm capitalize">{subject}</span>
                    <span className="text-slate-500 text-xs">
                      {stats.total} 题 | {(stats.accuracy * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="w-full bg-slate-700 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${
                        stats.accuracy > 0.8 ? 'bg-emerald-500' :
                        stats.accuracy > 0.6 ? 'bg-amber-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${stats.accuracy * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 中间 - 个性化建议 */}
        <div className="space-y-6">
          <div className="card p-6">
            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-primary-400" />
              今日学习建议
            </h3>
            {recommendations?.length > 0 ? (
              <div className="space-y-4">
                {recommendations.map((rec, index) => (
                  <div
                    key={index}
                    className="p-4 bg-slate-800/50 rounded-xl hover:bg-slate-800 transition-colors cursor-pointer"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          rec.priority === 'urgent' ? 'bg-red-500/20 text-red-400' :
                          rec.priority === 'high' ? 'bg-amber-500/20 text-amber-400' :
                          'bg-blue-500/20 text-blue-400'
                        }`}>
                          {rec.priority === 'urgent' ? '紧急' :
                           rec.priority === 'high' ? '重要' : '建议'}
                        </span>
                        <span className="text-slate-500 text-xs">
                          {rec.subject}
                        </span>
                      </div>
                      <span className="text-slate-500 text-xs flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {rec.estimated_time_minutes} 分钟
                      </span>
                    </div>
                    <h4 className="text-white font-medium mb-1">{rec.title}</h4>
                    <p className="text-slate-400 text-sm">{rec.description}</p>

                    {rec.knowledge_points?.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1">
                        {rec.knowledge_points.map((kp, i) => (
                          <span key={i} className="badge-primary text-xs">
                            {kp}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <Zap className="w-12 h-12 text-primary-400 mx-auto mb-3" />
                <p className="text-slate-400">正在为你生成学习建议...</p>
              </div>
            )}
          </div>

          {/* AI 点评 */}
          {summary?.ai_comment && (
            <div className="card p-6 bg-gradient-to-br from-primary-500/10 to-accent-500/10 border-primary-500/30">
              <h3 className="text-white font-semibold mb-3 flex items-center gap-2">
                <Brain className="w-5 h-5 text-primary-400" />
                学习小书童的话
              </h3>
              <p className="text-slate-300 whitespace-pre-line">
                {summary.ai_comment}
              </p>
            </div>
          )}
        </div>

        {/* 右侧 - 学习计划 */}
        <div className="space-y-6">
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Calendar className="w-5 h-5 text-emerald-400" />
                学习计划
              </h3>
              <select
                value={planDays}
                onChange={(e) => setPlanDays(Number(e.target.value))}
                className="input w-auto text-sm py-1 px-2"
              >
                <option value={7}>7 天</option>
                <option value={14}>14 天</option>
                <option value={30}>30 天</option>
              </select>
            </div>

            {studyPlan?.daily_tasks?.length > 0 ? (
              <div className="space-y-4 max-h-[600px] overflow-y-auto">
                {studyPlan.daily_tasks.slice(0, 7).map((day, dayIndex) => (
                  <div key={dayIndex} className="border-l-2 border-slate-700 pl-4">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-3 h-3 bg-primary-500 rounded-full -ml-[22px]" />
                      <span className="text-white font-medium">
                        {new Date(day.date).toLocaleDateString('zh-CN', {
                          month: 'short',
                          day: 'numeric',
                          weekday: 'short'
                        })}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {day.tasks.map((task, taskIndex) => (
                        <div
                          key={taskIndex}
                          className="p-3 bg-slate-800/50 rounded-lg flex items-center justify-between"
                        >
                          <div className="flex-1">
                            <p className="text-slate-300 text-sm">{task.title}</p>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-slate-500 text-xs">
                                {task.subject}
                              </span>
                              <span className="text-slate-600">•</span>
                              <span className="text-slate-500 text-xs">
                                {task.estimated_minutes} 分钟
                              </span>
                            </div>
                          </div>
                          <ChevronRight className="w-4 h-4 text-slate-600" />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <Calendar className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                <p className="text-slate-400">正在生成学习计划...</p>
              </div>
            )}

            {studyPlan && (
              <div className="mt-4 pt-4 border-t border-slate-700">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">预计总时长</span>
                  <span className="text-white font-medium">
                    {studyPlan.total_estimated_hours?.toFixed(1)} 小时
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* 强项展示 */}
          {profile?.strong_points?.length > 0 && (
            <div className="card p-6">
              <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                <Award className="w-5 h-5 text-emerald-400" />
                你的强项
              </h3>
              <div className="flex flex-wrap gap-2">
                {profile.strong_points.map((point, index) => (
                  <span
                    key={index}
                    className="px-3 py-2 bg-emerald-500/10 text-emerald-400 rounded-lg text-sm flex items-center gap-1"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    {point}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  clearOpportunityAnswersCache,
  fetchOpportunityAnswers,
  listQuestionIdsWithConflictsInApiResponse,
  normalizeAnswerRow,
} from '../services/opportunityAnswersApi'
import { fetchOpportunityQuestions } from '../services/opportunityReviewApi'
import { mergeAnswerRowWithQuestionsCatalog } from '../utils/opportunityReviewMeta'

/**
 * Single coordinated load: GET /answers and GET /questions together (Promise.all).
 * Uses cached/deduped fetchers so React Strict Mode and effect re-runs do not multiply network calls.
 *
 * @param {string|null|undefined} opportunityId
 * @param {{ enabled?: boolean }} [options]
 */
export function useOpportunityQaBundle(opportunityId, options = {}) {
  const { enabled = true } = options
  const answersOpportunityIdRef = useRef(null)
  const [answersData, setAnswersData] = useState(null)
  const [questionsData, setQuestionsData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [answersError, setAnswersError] = useState(null)
  const [questionsError, setQuestionsError] = useState(null)

  const load = useCallback(async (bypassCache = false) => {
    if (!enabled || !opportunityId) {
      setAnswersData(null)
      setQuestionsData(null)
      setAnswersError(null)
      setQuestionsError(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setAnswersError(null)
    setQuestionsError(null)

    const [ra, rq] = await Promise.allSettled([
      fetchOpportunityAnswers(opportunityId, { bypassCache }),
      fetchOpportunityQuestions(opportunityId, { bypassCache }),
    ])

    if (ra.status === 'fulfilled') {
      const json = ra.value
      const oid = String(json.opportunity_id ?? opportunityId ?? '')
      const apiConflictQids = listQuestionIdsWithConflictsInApiResponse(json)

      if (import.meta.env.DEV) {
        const qOk = rq.status === 'fulfilled'
        console.info(
          '%c[Data source: summary]%c Q&A bundle for opportunity',
          'color:#0f766e;font-weight:800',
          'color:inherit',
          oid,
          {
            answers: 'Swagger / live API — GET /opportunities/{id}/answers',
            conflictsFromApiBody:
              apiConflictQids.length > 0
                ? apiConflictQids.join(', ')
                : 'none (raw response had no conflicts[] / conflict_id)',
            questionsMerge: qOk
              ? 'Swagger / live API — GET /opportunities/{id}/questions (merged onto answer rows for types/options)'
              : 'not loaded — using answers row fields only',
          },
        )
      }

      let answers = (json.answers || []).map(r => normalizeAnswerRow(r, { opportunityId: oid }))

      if (rq.status === 'fulfilled') {
        const qPayload = rq.value
        const qList = qPayload?.questions
        if (Array.isArray(qList) && qList.length > 0) {
          const qById = new Map()
          for (const q of qList) {
            if (q?.question_id != null) qById.set(String(q.question_id), q)
          }
          answers = answers.map(a => mergeAnswerRowWithQuestionsCatalog(a, qById.get(String(a.question_id))))
        }
      }

      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: derived]%c Normalized answers (API only)',
          'color:#64748b;font-weight:700',
          'color:inherit',
          { opportunity_id: json.opportunity_id ?? opportunityId, answers },
        )
      }
      setAnswersData({
        opportunity_id: json.opportunity_id ?? opportunityId,
        answers,
        human_count: typeof json.human_count === 'number' ? json.human_count : undefined,
        ai_count: typeof json.ai_count === 'number' ? json.ai_count : undefined,
        total_questions: typeof json.total_questions === 'number' ? json.total_questions : undefined,
        percentage: typeof json.percentage === 'number' ? json.percentage : undefined,
        human_percentage: typeof json.human_percentage === 'number' ? json.human_percentage : undefined,
        ai_percentage: typeof json.ai_percentage === 'number' ? json.ai_percentage : undefined,
      })
      setAnswersError(null)
    } else {
      setAnswersData(null)
      const r = ra.reason
      const err = r instanceof Error ? r : new Error(String(r))
      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / API]%c GET /answers failed — no bundle payload',
          'color:#b45309;font-weight:700',
          'color:inherit',
          err.message,
        )
      }
      setAnswersError(err)
    }

    if (rq.status === 'fulfilled') {
      setQuestionsData(rq.value)
      setQuestionsError(null)
    } else {
      setQuestionsData(null)
      const r = rq.reason
      const err = r instanceof Error ? r : new Error(String(r))
      if (import.meta.env.DEV) {
        console.info(
          '%c[Data source: Swagger / API]%c GET /questions failed — question catalog merge skipped',
          'color:#b45309;font-weight:700',
          'color:inherit',
          err.message,
        )
      }
      setQuestionsError(err)
    }

    setLoading(false)
  }, [enabled, opportunityId])

  useEffect(() => {
    if (!enabled || !opportunityId) return
    if (answersOpportunityIdRef.current !== opportunityId) {
      clearOpportunityAnswersCache(opportunityId)
      answersOpportunityIdRef.current = opportunityId
    }
  }, [enabled, opportunityId])

  useEffect(() => {
    load(false)
  }, [load])

  const refetch = useCallback(() => load(true), [load])

  return {
    answersData,
    questionsData,
    loading,
    answersError,
    questionsError,
    refetch,
  }
}

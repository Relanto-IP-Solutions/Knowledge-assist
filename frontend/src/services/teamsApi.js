import { api } from './apiClient'

function extractDetail(e) {
  return e?.response?.data?.detail || e?.message || 'Something went wrong.'
}

function apiError(e) {
  const err = new Error(extractDetail(e))
  err.status = e?.response?.status
  return err
}

/** Fetch all teams. GET /teams */
export async function listTeams() {
  try {
    const { data } = await api.get('/teams')
    return data.teams ?? data ?? []
  } catch (e) {
    throw apiError(e)
  }
}

/** Fetch a single team by ID. GET /teams/{id} */
export async function getTeam(id) {
  try {
    const { data } = await api.get(`/teams/${encodeURIComponent(id)}`)
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/** Fetch all users available for team assignment. GET /teams/users */
export async function listTeamUsers() {
  try {
    const { data } = await api.get('/teams/users')
    return data.users ?? data ?? []
  } catch (e) {
    throw apiError(e)
  }
}

/** Create a new team. POST /teams */
export async function createTeam({ name, members }) {
  const trimmed = String(name ?? '').trim()
  if (!trimmed) throw Object.assign(new Error('Team name is required.'), { status: 400 })
  try {
    const { data } = await api.post('/teams', {
      name: trimmed,
      members: members ?? [],
    })
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/** Update team members and leads. PUT /teams/{id} */
export async function updateTeam(id, { name, members }) {
  try {
    const { data } = await api.put(`/teams/${encodeURIComponent(id)}`, {
      name,
      members,
    })
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/** Assign opportunities to a team. POST /teams/{id}/assign-opportunities */
export async function assignOpportunities(id, opportunityIds, { allowReassignment = true } = {}) {
  try {
    const { data } = await api.post(`/teams/${encodeURIComponent(id)}/assign-opportunities`, {
      opportunity_ids: opportunityIds,
      allow_reassignment: allowReassignment,
    })
    return data
  } catch (e) {
    throw apiError(e)
  }
}

/** Fetch unassigned opportunities. GET /opportunities/unassigned */
export async function listUnassignedOpportunities() {
  try {
    const { data } = await api.get('/opportunities/unassigned')
    return data.opportunities ?? data ?? []
  } catch (e) {
    throw apiError(e)
  }
}

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScoreHistoryChart } from '../components/ui/ScoreHistoryChart'

describe('ScoreHistoryChart', () => {
  it('renders nothing until at least two scores exist', () => {
    const { container } = render(<ScoreHistoryChart scoreHistory={[72]} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders the desktop score progression chart', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })

    render(<ScoreHistoryChart scoreHistory={[52, 68, 91]} />)

    expect(screen.getByText('Score progression across 3 optimisation passes')).toBeInTheDocument()
    expect(screen.getAllByText('52')).not.toHaveLength(0)
    expect(screen.getAllByText('91')).not.toHaveLength(0)
    expect(screen.getByText('(+39 points)')).toBeInTheDocument()
  })

  it('renders compact mobile summary on narrow screens', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })

    render(<ScoreHistoryChart scoreHistory={[71, 84]} />)

    expect(screen.getByText('Score improved by +13 points across 2 passes')).toBeInTheDocument()
  })
})

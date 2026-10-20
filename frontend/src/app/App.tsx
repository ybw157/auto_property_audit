import { ErrorBoundary } from '../components/ErrorBoundary'
import { AppRouter } from '../router'

export function App() {
  return (
    <ErrorBoundary>
      <AppRouter />
    </ErrorBoundary>
  )
}

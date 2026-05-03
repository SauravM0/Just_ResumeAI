# Frontend E2E QA Checklist

## Prerequisites
- [ ] Backend running (default: http://localhost:8000)
- [ ] Frontend running (default: http://localhost:5173)
- [ ] pdflatex installed on system

---

## Core Flow Tests

### 1. Application Startup
- [ ] 1. Start backend: `cd backend && python -m uvicorn app.main:app --reload`
- [ ] 2. Start frontend: `cd frontend && npm run dev`
- [ ] 3. Open browser to http://localhost:5173
- [ ] 4. No console errors on page load

### 2. Profile Creation
- [ ] 4. Create or load master profile
  - [ ] Fill in contact info (name, email, phone)
  - [ ] Add work experience with bullets
  - [ ] Add education
  - [ ] Add skills
  - [ ] Save profile

### 3. JD Input & Resume Generation
- [ ] 5. Paste OBDX JD:
  ```
  Designation : OBDX DEVELOPER :

  Skills:
  PL/SQL
  Java/Microservices
  UI/UX development
  DevOps
  OBDX hands on experience

  Role Description:
  Installation of OBDX
  Development of CEMLIs for OBDX
  Troubleshooting of issues
  Deployment to non-production environments
  Should have knowledge of DevOps process, GIT, Jenkins
  Should have working knowledge on UI/UX development and using Development Workbench
  Should have extensive knowledge on Java/Microservices development w.r.t OBDX and using extensibility
  Should have hands-on experience with Mobile App development for iOS/Android
  Working knowledge of UK Open Banking will be an advantage
  ```
- [ ] 6. Click "Generate ATS Resume"
- [ ] 7. Confirm Resume Review page opens
- [ ] 8. Confirm ATS score panel appears (shows overall score)
- [ ] 9. Confirm "Missing Keywords" section appears
- [ ] 10. Confirm "Included Keywords" section appears
- [ ] 11. **NEGATIVE**: Confirm NO evidence/truthfulness panel appears
- [ ] 12. Click "Regenerate" for higher ATS score
- [ ] 13. Confirm resume content updates (new bullets/summary)

### 4. PDF Generation
- [ ] 14. Click "Approve & Generate PDF"
- [ ] 15. Confirm loading spinner appears
- [ ] 16. Confirm success message: "PDF generated successfully"
- [ ] 17. Confirm PDF preview loads in iframe/modal
- [ ] 18. Click "Download PDF" button
- [ ] 19. Confirm PDF downloads with valid content
- [ ] 20. **NEGATIVE**: Verify no corrupted bullet symbols (Â¤, Â®, Â©)
- [ ] 21. **NEGATIVE**: Verify no empty sections (empty itemize blocks)

### 5. Cover Letter
- [ ] 22. Navigate to Cover Letter page
- [ ] 23. Confirm cover letter text generates
- [ ] 24. Click "Regenerate" - confirm new version generates
- [ ] 25. Click "Copy" button - confirm text copies to clipboard

### 6. Session Persistence
- [ ] 26. Refresh browser (F5 or Ctrl+R)
- [ ] 27. Confirm session state persists (profile, JD, resume still visible)
- [ ] 28. Confirm no data loss after refresh

---

## Common Failure Checks

### Backend Issues
| Check | Symptom | Fix |
|-------|---------|-----|
| Backend route missing | 404 error in Network tab | Check `app/api/v1/endpoints/` for route definition |
| CORS issue | Network error, blocked by CORS | Check `app/main.py` CORS middleware configuration |
| pdflatex not installed | "pdflatex not found" in response | Install MiKTeX/TeX Live, add to PATH |

### PDF Issues
| Check | Symptom | Fix |
|-------|---------|-----|
| PDF compile error | "compile_errors" in API response | Check LaTeX syntax, remove unsupported commands |
| Empty itemize | `\begin{itemize}\end{itemize}` in LaTeX | Ensure all sections have at least one bullet |
| Corrupted bullets | `Â¤`, `Â®`, `Â©` in rendered PDF | Check `app/services/latex_render_service.py` bullet formatting |

### Frontend State Issues
| Check | Symptom | Fix |
|-------|---------|-----|
| Zustand state missing | Empty UI after navigation | Check `src/store/` for store hydration |
| API field mismatch | Console errors, undefined values | Verify `src/lib/api.ts` matches backend schema |

### Network Issues
| Check | Symptom | Fix |
|-------|---------|-----|
| Wrong port | Connection refused | Confirm backend on 8000, frontend on 5173 |
| Backend down | App unresponsive | Restart backend server |

---

## Test Data

### OBDX JD (Primary Test Case)
```
Designation : OBDX DEVELOPER :

Skills:
PL/SQL
Java/Microservices
UI/UX development
DevOps
OBDX hands on experience

Role Description:
Installation of OBDX
Development of CEMLIs for OBDX
Troubleshooting of issues
Deployment to non-production environments
Should have knowledge of DevOps process, GIT, Jenkins
Should have working knowledge on UI/UX development and using Development Workbench
Should have extensive knowledge on Java/Microservices development w.r.t OBDX and using extensibility
Should have hands-on experience with Mobile App development for iOS/Android
Working knowledge of UK Open Banking will be an advantage
```

### Expected Results
- **Job Title**: "OBDX Developer" (no "Designation" prefix)
- **ATS Score**: > 0 (not capped by truthfulness)
- **Keywords**: PL/SQL, Java, Microservices, OBDX, DevOps, Jenkins, CEMLI, iOS, Android
- **No warnings**: truthfulness, evidence, blockers

---

## Browser Support
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

## Screen Sizes
- [ ] Desktop (1920x1080)
- [ ] Laptop (1366x768)
- [ ] Mobile (375x667) - verify responsive layout
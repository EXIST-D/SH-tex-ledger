# Changes (original -> delivered sources)

## main.tex (modified, +2 -1)
```diff
--- a/main.tex
+++ b/main.tex
@@ -2,4 +2,5 @@
 \usepackage[utf8]{inputenc}
+\usepackage{amsmath}
+\usepackage{booktabs}
 \usepackage{hyperref}
-\usepackage{amsmath}
 \title{A Small Study of Rooftop Cooling (INVENTED example project)}
```
## sec/intro.tex (modified, +3 -3)
```diff
--- a/sec/intro.tex
+++ b/sec/intro.tex
@@ -1,5 +1,5 @@
 \section{Introduction}\label{sec:intro}
-{\bf Green roofs} lower summer cooling loads \cite{okafor2011}. We measure the effect
-in 12 houses and report it in Section~\ref{sec:methods}. For a loss $L$ we write
-$$ L = \sum_i (y_i - \hat y_i)^2 $$
+\textbf{Green roofs} lower summer cooling loads \cite{okafor2011}. We measure the effect
+in 12 houses and report it in Section~\ref{sec:method}. For a loss $L$ we write
+\[ L = \sum_i (y_i - \hat y_i)^2 \]
 and refer to it as Eq.~\eqref{eq:loss}.
```
## sec/method.tex (modified, +4 -5)
```diff
--- a/sec/method.tex
+++ b/sec/method.tex
@@ -1,7 +1,6 @@
 \section{Method}\label{sec:method}
-Data are stored in results_final.csv. Table~\ref{tab:main} lists the houses.
-\begin{table}[h]
+Data are stored in results\_final.csv. Table~\ref{tab:main} lists the houses.
+\begin{table}[htbp]
 \centering
-\label{tab:main}
-\caption{Cooling energy saving by house type.
+\caption{Cooling energy saving by house type.}\label{tab:main}
 \begin{tabular}{lcc}
@@ -9,3 +8,3 @@
 House & Saving (\%) & Samples \\
-terraced & 14 & 12 & 3 \\
+terraced & 14 & 12 \\
 detached & 9 & 8 \\
```

## Fixes applied by `fix` (each verified by a compile)
- sec/intro.tex: display_dollars: $$..$$ -> \[..\]
- sec/intro.tex: old font switches {\bf X} -> \textbf{X}
- sec/method.tex: float placement [h] -> [htbp]
- main.tex: hyperref moved after the other packages
- main.tex: missing package: \usepackage{booktabs} added (\toprule is used and the package is not loaded)
- sec/method.tex: \label moved after \caption

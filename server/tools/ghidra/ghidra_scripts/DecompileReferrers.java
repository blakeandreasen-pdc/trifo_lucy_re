// Decompile every function that references (calls OR takes the address of) functions whose
// names match a regex - finds handler tables built from function pointers.
// Usage (headless): -postScript DecompileReferrers.java "<name regex>" /path/to/out.c
// @category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

public class DecompileReferrers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Pattern pat = Pattern.compile(args[0]);
        PrintWriter out = new PrintWriter(args[1]);
        Map<Function, StringBuilder> refs = new LinkedHashMap<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (!pat.matcher(f.getName()).matches()) continue;
            for (Reference r : getReferencesTo(f.getEntryPoint())) {
                Function from = getFunctionContaining(r.getFromAddress());
                String where = from != null ? "" : " (data @ " + r.getFromAddress() + ")";
                out.println("// ref to " + f.getName(true) + " from " + r.getFromAddress() + " type " + r.getReferenceType() + where);
                if (from != null) refs.computeIfAbsent(from, k -> new StringBuilder()).append(f.getName()).append(' ');
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (Map.Entry<Function, StringBuilder> e : refs.entrySet()) {
            DecompileResults res = di.decompileFunction(e.getKey(), 180, monitor);
            out.println("// ===== referrer " + e.getKey().getName(true) + " @ " + e.getKey().getEntryPoint() + "  refs: " + e.getValue());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed: " + res.getErrorMessage());
        }
        out.close();
        println("decompiled " + refs.size() + " referrers -> " + args[1]);
    }
}

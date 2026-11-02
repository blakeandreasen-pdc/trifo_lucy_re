// Decompile all callers (one level) of the functions whose names match a regex.
// Usage (headless): -postScript DecompileCallers.java "<callee name regex>" /path/to/out.c
// @category Analysis
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Pattern;

public class DecompileCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Pattern pat = Pattern.compile(args[0]);
        PrintWriter out = new PrintWriter(args[1]);
        Set<Function> callers = new LinkedHashSet<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (pat.matcher(f.getName()).matches()) {
                callers.addAll(f.getCallingFunctions(monitor));
            }
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (Function c : callers) {
            DecompileResults res = di.decompileFunction(c, 120, monitor);
            out.println("// ===== caller " + c.getName() + " @ " + c.getEntryPoint());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "// failed: " + res.getErrorMessage());
        }
        out.close();
        println("decompiled " + callers.size() + " callers -> " + args[1]);
    }
}
